using System;
using System.Runtime.InteropServices;

[Flags]
internal enum GestureAction { None = 0, Consume = 1, ReleaseModifier = 2, Next = 4, Previous = 8, HoldForward = 16, HoldBackward = 32 }

internal sealed class KeySnapshot
{
    private readonly bool[] held = new bool[256];
    private int otherCount;
    internal bool Modified { get { return held[0x10] || held[0x11] || held[0xA0] || held[0xA1]
        || held[0xA2] || held[0xA3] || held[0x5B] || held[0x5C]; } }
    internal bool Alt { get { return held[0x12] || held[0xA4] || held[0xA5]; } }
    internal int ModifierFlags { get { return (held[0x11] || held[0xA2] || held[0xA3] ? KeyChord.Control : 0)
        | (Alt ? KeyChord.Alt : 0) | (held[0x10] || held[0xA0] || held[0xA1] ? KeyChord.Shift : 0)
        | (held[0x5B] || held[0x5C] ? KeyChord.Win : 0); } }
    internal bool OtherKeysExcept(int family)
    {
        int total = otherCount + (held[0x12] ? 1 : 0) + (held[0xA4] ? 1 : 0) + (held[0xA5] ? 1 : 0);
        if (family == 0x12) total -= (held[0x12] ? 1 : 0) + (held[0xA4] ? 1 : 0) + (held[0xA5] ? 1 : 0);
        else if (family == 0x11) total -= (held[0x11] ? 1 : 0) + (held[0xA2] ? 1 : 0) + (held[0xA3] ? 1 : 0);
        else total -= (held[0x10] ? 1 : 0) + (held[0xA0] ? 1 : 0) + (held[0xA1] ? 1 : 0);
        return total != 0;
    }
    internal bool MouseHeld { get { return held[1] || held[2] || held[4] || held[5] || held[6]; } }
    internal bool OtherKeysHeld { get { return otherCount != 0; } }
    internal void Clear() { Array.Clear(held, 0, held.Length); otherCount = 0; }
    internal bool IsDown(int key) { return key >= 0 && key < held.Length && held[key]; }
    internal void Set(int key, bool down)
    {
        if (key < 0 || key >= held.Length || held[key] == down) return;
        held[key] = down;
        if (key >= 8 && !ModifierGestures.IsAlt(key)) otherCount += down ? 1 : -1;
    }
    internal static int Normalize(int key, uint flags, uint scan)
    {
        if (key == 0x12) return (flags & 1) != 0 ? 0xA5 : 0xA4;
        if (key == 0x11) return (flags & 1) != 0 ? 0xA3 : 0xA2;
        if (key == 0x10) return scan == 0x36 ? 0xA1 : 0xA0;
        return key;
    }
    internal static void SelfTest()
    {
        var k = new KeySnapshot();
        k.Set(0xA4, true);
        if (!k.Alt || k.OtherKeysHeld || k.Modified) throw new Exception("Alt snapshot.");
        k.Set(0xDD, true); k.Set(0xDD, true); k.Set(0xDD, false);
        if (k.OtherKeysHeld) throw new Exception("Repeated key snapshot count.");
        k.Set(0xA2, true); k.Set(1, true);
        if (!k.Modified || !k.OtherKeysHeld || !k.MouseHeld) throw new Exception("Modifier/mouse snapshot.");
        k.Clear();
        if (k.Alt || k.OtherKeysHeld || k.Modified || k.MouseHeld) throw new Exception("Snapshot reset.");
        if (Normalize(0x12, 0, 0) != 0xA4 || Normalize(0x12, 1, 0) != 0xA5
            || Normalize(0x11, 1, 0) != 0xA3 || Normalize(0x10, 0, 0x36) != 0xA1)
            throw new Exception("Modifier normalization.");
    }
}

internal sealed class ModifierGestures
{
    internal readonly int Family, NextKey, PreviousKey;
    private readonly uint tapWait, shortPress;
    internal ModifierGestures(int family = 0x12, int next = 0xDD, int previous = 0xDB, uint wait = 100, uint shortMax = 300)
    { Family = family; NextKey = next; PreviousKey = previous; tapWait = wait; shortPress = shortMax; }
    internal bool IsActivation(int key) { return KeyChord.InFamily(key, Family); }
    internal const uint OwnInputMarker = 0x43535043;
    internal const uint TapMaxMilliseconds = 300;
    // B and double-press arbitration share one window: once B has been sent,
    // a later second press cannot undo it and still match the schematic.
    internal const uint DoublePressMilliseconds = 100;
    private int heldModifier, lastModifier;
    private uint started, released;
    private bool eligible, secondPress, dialUsed, pendingB, nextDown, previousDown, conflictingModifier;
    private bool ownerInjected;
    private bool ordinaryShortcutUsed;
    private int nestedInjectedModifier;
    private bool pendingInjectedModifier;
    internal bool DialActive { get { return secondPress && heldModifier != 0 && !conflictingModifier; } }
    internal bool OrdinaryHeld { get { return !secondPress && heldModifier != 0 && !conflictingModifier; } }
    internal bool HoldReady(uint now) { return OrdinaryHeld && unchecked(now - started) > shortPress; }
    internal static bool IsAlt(int key) { return key == 0xA4 || key == 0xA5 || key == 0x12; }

    internal void Reset()
    {
        heldModifier = lastModifier = 0;
        eligible = secondPress = dialUsed = pendingB = nextDown = previousDown = conflictingModifier = false;
        ownerInjected = pendingInjectedModifier = ordinaryShortcutUsed = false; nestedInjectedModifier = 0;
    }
    internal void CancelTap() { eligible = pendingB = false; dialUsed = true; }
    internal bool Poll(uint now)
    {
        if (!pendingB || heldModifier != 0 || unchecked(now - released) < tapWait) return false;
        pendingB = false;
        return true;
    }
    internal GestureAction InputEvent(Native.KBDLLHOOKSTRUCT input, bool down, bool alone)
    {
        // Device-generated input is accepted, including lower-integrity injected
        // events. Ignore only output bearing this program's private marker.
        if (input.dwExtraInfo.ToUInt64() == OwnInputMarker) return GestureAction.None;
        return KeyEvent((int)input.vkCode, down, input.time, alone, (input.flags & 0x10) != 0);
    }
    internal GestureAction KeyEvent(int key, bool down, uint time, bool alone, bool injected = false)
    {
        if (!IsActivation(key))
        {
            bool ordinaryHold = heldModifier != 0 && !secondPress && !conflictingModifier;
            // Capture both edges of a dial bracket. Remember its release even
            // if Alt is released first, and suppress key auto-repeat.
            if (key == NextKey || key == PreviousKey)
            {
                bool captured = key == NextKey ? nextDown : previousDown;
                if (!down && captured)
                {
                    if (key == NextKey) nextDown = false; else previousDown = false;
                    return GestureAction.Consume;
                }
                // Software dials may emit several injected down events before
                // their up events. Each injected down is a notch, whereas a
                // physical keyboard hold still has auto-repeat suppression.
                if (down && captured && !(injected && (DialActive || ordinaryHold) && alone)) return GestureAction.Consume;
                if (down && (DialActive || ordinaryHold) && alone)
                {
                    // Commit a nested Alt packet only when its bracket arrives.
                    // Unpaired Alt key repeats must not keep dial mode latched.
                    if (injected && pendingInjectedModifier) { nestedInjectedModifier++; pendingInjectedModifier = false; }
                    CancelTap();
                    if (key == NextKey) nextDown = true; else previousDown = true;
                    if (DialActive)
                        return GestureAction.Consume | (key == NextKey ? GestureAction.Next : GestureAction.Previous);
                    ordinaryShortcutUsed = true;
                    return GestureAction.Consume | (key == NextKey ? GestureAction.HoldForward : GestureAction.HoldBackward);
                }
            }
            if (down && key != NextKey && key != PreviousKey) pendingInjectedModifier = false;
            CancelTap();
            return GestureAction.None;
        }
        if (down)
        {
            // Holding/repeating the same Alt never counts as a second press.
            if (heldModifier == key)
            {
                // A controller's Alt+bracket macro can wrap each notch in its
                // own Alt-down/up pair while the main button remains held.
                if (secondPress && injected) pendingInjectedModifier = true;
                return secondPress ? GestureAction.Consume : GestureAction.None;
            }
            if (heldModifier != 0)
            {
                CancelTap(); conflictingModifier = true;
                return GestureAction.None;
            }
            secondPress = pendingB && lastModifier == key && alone
                && unchecked(time - released) < tapWait;
            pendingB = false;
            heldModifier = key; started = time; eligible = alone; dialUsed = conflictingModifier = false;
            ownerInjected = injected; pendingInjectedModifier = ordinaryShortcutUsed = false; nestedInjectedModifier = 0;
            // Only the second press is captured. A first/ordinary Alt hold
            // goes straight to CSP, retaining its normal modifier behavior.
            return secondPress ? GestureAction.Consume : GestureAction.None;
        }
        if (heldModifier != key) return GestureAction.None;
        if (secondPress && injected)
        {
            pendingInjectedModifier = false;
            if (nestedInjectedModifier > 0) { nestedInjectedModifier--; return GestureAction.Consume; }
            // A software macro cannot release a genuinely held keyboard Alt.
            if (!ownerInjected) return GestureAction.Consume;
        }
        bool wasSecond = secondPress;
        bool shortTap = eligible && alone && !dialUsed && unchecked(time - started) <= shortPress;
        heldModifier = 0; secondPress = false;
        nestedInjectedModifier = 0;
        pendingInjectedModifier = false;
        pendingB = shortTap; released = time; lastModifier = key;
        // Two short taps with no dial use resolve to one B. A held second press
        // or any dial use resolves only to dial mode, with no leading/trailing B.
        // F/S temporarily restore the held native modifier. Mask its eventual
        // release so it does not open CSP's menu bar after the remapped command.
        if (wasSecond || shortTap || ordinaryShortcutUsed) return GestureAction.Consume | GestureAction.ReleaseModifier;
        return GestureAction.None;
    }

    private static void Expect(bool condition, string message) { if (!condition) throw new Exception(message); }
    internal static void SelfTest()
    {
        var g = new ModifierGestures();
        GestureAction release = GestureAction.Consume | GestureAction.ReleaseModifier;
        // Schematic 1: short pulse -> one B after the double-press window.
        Expect(g.KeyEvent(0xA4, true, 100, true) == GestureAction.None, "Initial Alt must pass.");
        Expect(g.KeyEvent(0xA4, false, 180, true) == release, "Mask single tap release.");
        Expect(!g.Poll(279) && g.Poll(280) && !g.Poll(900), "100 ms single tap B timing/count.");
        // Schematic 2: one long pulse -> native Alt, no B or dial.
        g.Reset(); g.KeyEvent(0xA4, true, 100, true);
        Expect(!g.DialActive && !g.Poll(600), "Ordinary Alt hold armed dial.");
        Expect(g.KeyEvent(0xA4, false, 900, true) == GestureAction.None && !g.Poll(1500), "Long hold generated B.");
        // Schematic 3: short pulse then held second pulse -> dial, never B.
        g.Reset(); g.KeyEvent(0xA4, true, 100, true); g.KeyEvent(0xA4, false, 180, true);
        Expect(g.KeyEvent(0xA4, true, 250, true) == GestureAction.Consume && g.DialActive, "Second press must capture Alt/arm dial.");
        Expect(!g.Poll(800), "First tap leaked B into dial gesture.");
        Expect(g.KeyEvent(0xDD, true, 900, true) == (GestureAction.Consume | GestureAction.Next), "Dial next.");
        Expect(g.KeyEvent(0xDD, true, 950, true) == GestureAction.Consume, "Dial repeat.");
        Expect(g.KeyEvent(0xDD, false, 970, true) == GestureAction.Consume, "Dial key release.");
        Expect(g.KeyEvent(0xDB, true, 1000, true) == (GestureAction.Consume | GestureAction.Previous), "Dial previous.");
        g.KeyEvent(0xA4, false, 1200, true);
        Expect(!g.DialActive && !g.Poll(2000), "Dial release leaked B.");
        Expect(g.KeyEvent(0xDB, false, 1250, true) == GestureAction.Consume, "Release bracket after Alt.");
        Expect(g.KeyEvent(0xDD, true, 1300, true) == GestureAction.None, "Bracket captured outside dial.");
        // Ordinary held Alt alone stays native; brackets send F/S, never cycle.
        g.Reset(); g.KeyEvent(0xA4, true, 100, true);
        Expect(g.KeyEvent(0xDD, true, 150, true) == (GestureAction.Consume | GestureAction.HoldForward), "_Alt+] must send F.");
        Expect(g.KeyEvent(0xA4, false, 200, true) == release && !g.Poll(1000), "F shortcut release masking/B cancellation.");
        Expect(g.KeyEvent(0xDD, false, 210, true) == GestureAction.Consume, "F shortcut bracket release.");
        g.Reset(); g.KeyEvent(0xA4, true, 100, true);
        Expect(g.KeyEvent(0xDB, true, 150, true) == (GestureAction.Consume | GestureAction.HoldBackward), "_Alt+[ must send S.");
        Expect(!g.DialActive, "Ordinary F/S shortcut armed dial cycling.");
        g.KeyEvent(0xDB, false, 160, true); g.KeyEvent(0xA4, false, 200, true);
        Expect(!g.Poll(1000), "S shortcut generated B.");
        foreach (int other in new int[] { 0x09, 0x73, 0x41 })
        {
            g.Reset(); g.KeyEvent(0xA4, true, 100, true);
            Expect(g.KeyEvent(other, true, 150, true) == GestureAction.None, "Other Alt shortcut changed.");
        }
        g.Reset(); g.KeyEvent(0xA4, true, 100, true);
        Expect(g.KeyEvent(0xDD, true, 150, false) == GestureAction.None, "Modified Alt bracket must pass through.");
        foreach (uint flags in new uint[] { 0, 0x10, 0x12 })
        {
            foreach (uint bracket in new uint[] { 0xDD, 0xDB })
            {
                g.Reset();
                var input = new Native.KBDLLHOOKSTRUCT { vkCode = 0xA4, flags = flags, time = 100 };
                g.InputEvent(input, true, true);
                input.vkCode = bracket; input.time = 150;
                GestureAction expected = GestureAction.Consume | (bracket == 0xDD ? GestureAction.HoldForward : GestureAction.HoldBackward);
                Expect(g.InputEvent(input, true, true) == expected, "Keyboard/device F/S command.");
                input.time = 160; g.InputEvent(input, false, true);
                input.vkCode = 0xA4; input.time = 200;
                Expect(g.InputEvent(input, false, true) == release && !g.Poll(1000), "F/S Alt release/B prevention.");
            }
        }
        g.Reset(); g.KeyEvent(0xA4, true, 100, true, true);
        for (uint i = 0; i < 100; i++)
            Expect(g.KeyEvent(0xDD, true, 150 + i, true, true) == (GestureAction.Consume | GestureAction.HoldForward), "Dropped rapid ordinary-hold F.");
        // Late second press is an ordinary Alt hold; native Alt auto-repeat is not a double press.
        g.Reset(); g.KeyEvent(0xA4, true, 100, true); g.KeyEvent(0xA4, false, 180, true);
        g.KeyEvent(0xA4, true, 581, true); Expect(!g.DialActive, "Late double press.");
        g.Reset(); g.KeyEvent(0xA4, true, 100, true); g.KeyEvent(0xA4, true, 250, true);
        Expect(!g.DialActive, "Held Alt repeat armed dial.");
        g.KeyEvent(0xA4, false, 500, true); Expect(!g.Poll(1000), "Repeat extended tap deadline.");
        // Activity and loss of focus cancel deferred B.
        foreach (int key in new int[] { 0x31, 0x70, 0x09, 0x11, 0x10, 0x42 })
        {
            g.Reset(); g.KeyEvent(0xA4, true, 100, true); g.KeyEvent(0xA4, false, 180, true);
            g.KeyEvent(key, true, 250, true); Expect(!g.Poll(1000), "Unrelated keyboard action left B pending.");
        }
        g.Reset(); g.KeyEvent(0xA4, true, 100, true); g.KeyEvent(0xA4, false, 180, true); g.CancelTap();
        Expect(!g.Poll(1000), "Mouse action left B pending.");
        g.KeyEvent(0xA4, true, 1100, true); g.KeyEvent(0xA4, false, 1180, true); g.Reset();
        Expect(!g.Poll(2000), "Focus change left B pending.");
        g.KeyEvent(0xA4, true, 100, false); g.KeyEvent(0xA4, false, 180, true);
        Expect(!g.Poll(1000), "Preheld modifier generated B.");
        // Keyboard and software dial input follow the same three gestures.
        foreach (uint flags in new uint[] { 0, 0x10, 0x12 })
        {
            g.Reset();
            var key = new Native.KBDLLHOOKSTRUCT { vkCode = 0xA4, flags = flags, time = 100 };
            g.InputEvent(key, true, true); key.time = 180; g.InputEvent(key, false, true);
            var own = new Native.KBDLLHOOKSTRUCT { vkCode = 0xA2, flags = 0x10, time = 200, dwExtraInfo = new UIntPtr(OwnInputMarker) };
            g.InputEvent(own, true, true);
            Expect(g.Poll(580), "Physical/device single tap or own-output filtering.");
            g.Reset(); key.time = 100; g.InputEvent(key, true, true); key.time = 180; g.InputEvent(key, false, true);
            key.time = 250; g.InputEvent(key, true, true);
            Expect(g.DialActive && !g.Poll(1000), "Device double hold.");
            key.time = 1200; g.InputEvent(key, false, true); Expect(!g.Poll(2000), "Device trailing B.");
        }
        g.Reset(); g.KeyEvent(0xA5, true, 100, true); g.KeyEvent(0xA5, false, 180, true);
        Expect(g.Poll(580), "Right Alt tap.");
        g.Reset(); g.KeyEvent(0xA4, true, UInt32.MaxValue - 99, true); g.KeyEvent(0xA4, false, 100, true);
        Expect(!g.Poll(199) && g.Poll(200), "Uptime rollover.");
        g.Reset(); g.KeyEvent(0xA4, true, 100, true); g.KeyEvent(0xA4, false, 180, true);
        g.KeyEvent(0xA4, true, 250, true); g.KeyEvent(0xA4, false, 300, true);
        Expect(!g.Poll(399) && g.Poll(400) && !g.Poll(800), "Two short taps without hold resolve once.");
        // Regression: rapid overlapping software notches are not keyboard repeats.
        g.Reset(); g.KeyEvent(0xA4, true, 100, true, true); g.KeyEvent(0xA4, false, 180, true, true);
        g.KeyEvent(0xA4, true, 250, true, true);
        for (uint i = 0; i < 100; i++)
            Expect((g.KeyEvent(0xDD, true, 300 + i, true, true) & GestureAction.Next) != 0, "Dropped rapid injected notch.");
        g.KeyEvent(0xDD, false, 450, true, true);
        // Regression: nested Alt+bracket packets must not terminate dial mode.
        foreach (bool ownerIsInjected in new bool[] { false, true })
        {
            g.Reset(); g.KeyEvent(0xA4, true, 100, true, ownerIsInjected); g.KeyEvent(0xA4, false, 180, true, ownerIsInjected);
            g.KeyEvent(0xA4, true, 250, true, ownerIsInjected);
            for (uint i = 0; i < 100; i++)
            {
                uint t = 300 + i * 5;
                g.KeyEvent(0xA4, true, t, true, true);
                Expect((g.KeyEvent(0xDD, true, t + 1, true, true) & GestureAction.Next) != 0, "Dropped wrapped dial packet.");
                g.KeyEvent(0xDD, false, t + 2, true, true);
                g.KeyEvent(0xA4, false, t + 3, true, true);
                Expect(g.DialActive, "Notch Alt-up released held button.");
            }
            g.KeyEvent(0xA4, false, 1000, true, ownerIsInjected);
            Expect(!g.DialActive && !g.Poll(2000), "Button release did not end optimized dial mode.");
        }
        g.Reset(); g.KeyEvent(0xA4, true, 100, true, true); g.KeyEvent(0xA4, false, 180, true, true);
        g.KeyEvent(0xA4, true, 250, true, true);
        g.KeyEvent(0xA4, true, 300, true, true); g.KeyEvent(0xA4, true, 400, true, true);
        g.KeyEvent(0xA4, false, 1000, true, true);
        Expect(!g.DialActive, "Unpaired software Alt repeats latched dial mode.");
    }
}


internal static class Native
{
    internal delegate void WinEventProc(IntPtr hook, uint ev, IntPtr hwnd, int obj, int child, uint thread, uint time);
    internal delegate IntPtr InputHookProc(int code, IntPtr message, IntPtr data);
    [DllImport("kernel32.dll", CharSet = CharSet.Auto)] internal static extern IntPtr GetModuleHandle(string name);
    [DllImport("kernel32.dll")] internal static extern uint GetTickCount();
    [DllImport("user32.dll", SetLastError = true)]
    internal static extern IntPtr SetWindowsHookEx(int type, InputHookProc callback, IntPtr module, uint thread);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool UnhookWindowsHookEx(IntPtr hook);
    [DllImport("user32.dll")] internal static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr message, IntPtr data);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool PostMessage(IntPtr hwnd, int message, IntPtr wParam, IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)] internal struct KBDLLHOOKSTRUCT
    { internal uint vkCode, scanCode, flags, time; internal UIntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Sequential)] internal struct MSLLHOOKSTRUCT
    { internal int x, y; internal uint mouseData, flags, time; internal UIntPtr dwExtraInfo; }
    [DllImport("user32.dll")] internal static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] internal static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] internal static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll", SetLastError = true)]
    internal static extern uint SendInput(uint count, INPUT[] inputs, int size);
    [DllImport("user32.dll", SetLastError = true)]
    internal static extern IntPtr SetWinEventHook(uint min, uint max, IntPtr module, WinEventProc proc, uint pid, uint thread, uint flags);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool UnhookWinEvent(IntPtr hook);
    [StructLayout(LayoutKind.Sequential)] internal struct INPUT { internal uint type; internal InputUnion data; }
    [StructLayout(LayoutKind.Explicit)] internal struct InputUnion
    {
        [FieldOffset(0)] internal KEYBDINPUT ki;
        [FieldOffset(0)] internal MOUSEINPUT mi;
    }
    [StructLayout(LayoutKind.Sequential)] internal struct KEYBDINPUT
    { internal ushort wVk, wScan; internal uint dwFlags, time; internal UIntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Sequential)] internal struct MOUSEINPUT
    { internal int dx, dy; internal uint mouseData, dwFlags, time; internal UIntPtr dwExtraInfo; }
}



