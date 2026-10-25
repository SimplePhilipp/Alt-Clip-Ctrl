using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

internal sealed class RuntimeProfile
{
    internal ModifierBinding Binding;
    internal ModifierGestures State;
    internal KeyChord Tap, Forward, Backward, HoldOutput, OrdinaryOutput;
    internal KeyChord NativeModifier;
    internal Native.INPUT[] TapInputs, ForwardInputs, BackwardInputs, ScrollForward, ScrollBackward, ScrollStartForward, ScrollStartBackward;
}

internal struct GestureResult
{
    internal GestureAction Action;
    internal int Profile;
}

internal sealed class ScrollSession
{
    private int profile = -1;
    private bool secondPress;
    private IntPtr window;
    internal void Reset() { profile = -1; window = IntPtr.Zero; }
    internal void Sync(RuntimeProfile[] profiles)
    {
        if (profile < 0) return;
        RuntimeProfile p = profiles[profile];
        if (!p.Binding.Enabled || (secondPress ? !p.State.DialActive || p.Binding.DoubleHoldMode != "Dial scrolling"
            : !p.State.OrdinaryHeld || p.Binding.HoldMode != "Dial scrolling")) Reset();
    }
    internal Native.INPUT[] Packet(RuntimeProfile[] profiles, int owner, bool second, IntPtr target, int direction)
    {
        bool first = profile != owner || secondPress != second || window != target;
        profile = owner; secondPress = second; window = target;
        RuntimeProfile p = profiles[owner];
        return first ? (direction > 0 ? p.ScrollStartForward : p.ScrollStartBackward)
            : (direction > 0 ? p.ScrollForward : p.ScrollBackward);
    }
    internal static void SelfTest()
    {
        foreach (bool second in new bool[] { false, true })
        for (int owner = 0; owner < 3; owner++)
        {
            var settings = AppSettings.Defaults(); settings.Modifiers[owner].HoldMode = settings.Modifiers[owner].DoubleHoldMode = "Dial scrolling";
            var bank = new GestureBank(settings); var keys = new KeySnapshot(); var session = new ScrollSession();
            int modifier = owner == 0 ? 0xA4 : owner == 1 ? 0xA2 : 0xA0;
            uint now = 100;
            if (second) { Event(bank, keys, modifier, true, now++); Event(bank, keys, modifier, false, now++); }
            Event(bank, keys, modifier, true, now++);
            int wheels = 0, keyboardEvents = 0;
            for (int i = 0; i < 10000; i++)
            {
                int direction = i % 3 == 0 ? -1 : 1, key = direction > 0 ? 0xDD : 0xDB;
                session.Sync(bank.Profiles);
                GestureResult result = Event(bank, keys, key, true, now++);
                GestureAction expected = second ? (direction > 0 ? GestureAction.Next : GestureAction.Previous)
                    : (direction > 0 ? GestureAction.HoldForward : GestureAction.HoldBackward);
                if ((result.Action & expected) == 0) throw new Exception("Fast scrolling lost a notch.");
                Native.INPUT[] packet = session.Packet(bank.Profiles, owner, second, new IntPtr(1), direction);
                foreach (Native.INPUT input in packet)
                {
                    if (input.type == 0) { wheels++; if (input.data.mi.mouseData != (direction > 0 ? 120u : unchecked((uint)-120))) throw new Exception("Fast scroll reordered direction."); }
                    else keyboardEvents++;
                }
                if (i > 0 && packet.Length != 1) throw new Exception("Steady scrolling injected extra keys.");
                Event(bank, keys, key, false, now++);
            }
            if (wheels != 10000 || keyboardEvents != (owner == 0 ? 4 : 2)) throw new Exception("Fast scroll event totals.");
            Event(bank, keys, modifier, false, now++); session.Sync(bank.Profiles);
            Event(bank, keys, modifier, true, now++);
            Native.INPUT[] fresh = session.Packet(bank.Profiles, owner, false, new IntPtr(1), 1);
            if (fresh.Length <= 1) throw new Exception("A new scroll gesture omitted modifier cleanup.");
            session.Reset();
            if (session.Packet(bank.Profiles, owner, false, new IntPtr(2), 1).Length <= 1) throw new Exception("Focus reset omitted modifier cleanup.");
        }
    }
    internal static GestureResult Event(GestureBank bank, KeySnapshot keys, int key, bool down, uint time)
    {
        bool captured = bank.Captured(key);
        GestureResult result = bank.Handle(new Native.KBDLLHOOKSTRUCT { vkCode = (uint)key, flags = 0x10, time = time }, down, keys);
        if (!(captured && bank.Captured(key))) keys.Set(key, down);
        return result;
    }
}

internal sealed class ToolCycle
{
    internal readonly List<ToolBinding> Tools;
    internal readonly KeyChord[] Chords;
    internal readonly Native.INPUT[][] Inputs;
    internal int Position = -1;
    private readonly Dictionary<int, int> shortcutIndex = new Dictionary<int, int>();
    internal ToolCycle(List<ToolBinding> tools)
    {
        Tools = tools; Chords = new KeyChord[tools.Count]; Inputs = new Native.INPUT[tools.Count][];
        for (int i = 0; i < tools.Count; i++) { Chords[i] = KeyChord.Parse(tools[i].Shortcut); Inputs[i] = InputBuilder.Build(Chords[i]); shortcutIndex[(Chords[i].Modifiers << 16) | Chords[i].Key] = i; }
    }
    internal int Index(int key, int modifiers)
    {
        int index; return shortcutIndex.TryGetValue((modifiers << 16) | key, out index) ? index : -1;
    }
    internal int Next(int direction) { return MainForm.NextIndex(Position, direction, Tools.Count); }
    internal string Name { get { return Position < 0 ? "unknown" : Tools[Position].Name; } }
    internal static void SelfTest()
    {
        AppSettings s = AppSettings.Defaults();
        s.Modifiers[1].Tools = new List<ToolBinding> { new ToolBinding { Name = "Fill", Shortcut = "F1" }, new ToolBinding { Name = "Brush", Shortcut = "4" } };
        s.Modifiers[2].Tools = new List<ToolBinding> { new ToolBinding { Name = "Select", Shortcut = "9" } };
        s.Validate(); var cycles = new List<ToolCycle>();
        foreach (ModifierBinding p in s.Modifiers) cycles.Add(new ToolCycle(p.Tools));
        cycles[0].Position = cycles[0].Next(1); cycles[0].Position = cycles[0].Next(1);
        cycles[1].Position = cycles[1].Next(-1); cycles[2].Position = cycles[2].Next(1);
        if (cycles[0].Position != 1 || cycles[1].Position != 1 || cycles[2].Position != 0) throw new Exception("Independent cycle anchors.");
        cycles[1].Position = cycles[1].Next(1);
        if (cycles[1].Position != 0 || cycles[0].Position != 1 || cycles[2].Position != 0) throw new Exception("Cycling moved another profile.");
        cycles[0].Position = cycles[0].Next(1);
        if (cycles[0].Position != 2) throw new Exception("Switching cycles lost the previous position.");
        if (cycles[0].Index(0x70, 0) != 9 || cycles[1].Index(0x70, 0) != 0 || cycles[2].Index(0x70, 0) != -1) throw new Exception("Per-cycle shortcut matching.");
        var copy = s.Clone(); copy.Validate();
        if (copy.Modifiers[1].Tools.Count != 2 || copy.Modifiers[2].Tools.Count != 1) throw new Exception("Separate cycles were not saved.");
        // Migration preserves order/shortcuts but creates independent objects.
        s = AppSettings.Defaults(); s.Tools = s.Modifiers[0].Tools;
        foreach (ModifierBinding p in s.Modifiers) p.Tools = null;
        s.MigrateCycles(); s.Modifiers[0].Tools[0].Name = "Changed";
        if (s.Modifiers[1].Tools[0].Name != "Pen" || s.Modifiers[2].Tools.Count != 20 || s.Tools != null) throw new Exception("Legacy cycle migration.");
    }
}

internal sealed class GestureBank
{
    internal RuntimeProfile[] Profiles;
    internal GestureBank(AppSettings settings) { Configure(settings); }
    internal void Configure(AppSettings settings)
    {
        var list = new List<RuntimeProfile>();
        foreach (ModifierBinding p in settings.Modifiers)
            list.Add(new RuntimeProfile { Binding = p, Tap = KeyChord.Parse(p.TapOutput), Forward = KeyChord.Parse(p.HoldNextOutput),
                Backward = KeyChord.Parse(p.HoldPreviousOutput), HoldOutput = KeyChord.ParseHold(p.DoubleHoldOutput), OrdinaryOutput = KeyChord.ParseHold(p.HoldOutput), State = new ModifierGestures(KeyChord.ModifierKey(p.Modifier),
                    KeyChord.Parse(p.NextInput).Key, KeyChord.Parse(p.PreviousInput).Key, (uint)p.TapWaitMs, (uint)p.ShortPressMs) });
        Profiles = list.ToArray();
        foreach (RuntimeProfile p in Profiles)
        {
            p.NativeModifier = KeyChord.ParseHold(p.Binding.Modifier);
            p.TapInputs = InputBuilder.Build(p.Tap); p.ForwardInputs = InputBuilder.Build(p.Forward); p.BackwardInputs = InputBuilder.Build(p.Backward);
            p.ScrollStartForward = InputBuilder.DialScroll(p.Binding, 1); p.ScrollStartBackward = InputBuilder.DialScroll(p.Binding, -1);
            p.ScrollForward = InputBuilder.Build(InputBuilder.ScrollOutput(p.Binding, 1)); p.ScrollBackward = InputBuilder.Build(InputBuilder.ScrollOutput(p.Binding, -1));
        }
    }
    internal bool NeedsTimer(int heldProfile)
    {
        for (int i = 0; i < Profiles.Length; i++)
        { RuntimeProfile p = Profiles[i]; if (p.Binding.Enabled && (p.State.TapPending || (p.Binding.HoldMode == "Hold a key" && p.State.OrdinaryHeld && heldProfile != i))) return true; }
        return false;
    }
    internal int DialOwner
    {
        get { for (int i = 0; i < Profiles.Length; i++) if (Profiles[i].Binding.Enabled && Profiles[i].State.DialActive) return i; return -1; }
    }
    internal bool Captured(int key)
    {
        foreach (RuntimeProfile p in Profiles)
            if (p.Binding.Enabled && p.State.IsActivation(key) && (p.State.DialActive || p.State.OrdinaryHeld)) return true;
        return false;
    }
    internal void Reset() { foreach (RuntimeProfile p in Profiles) p.State.Reset(); }
    internal void CancelTap() { foreach (RuntimeProfile p in Profiles) p.State.CancelTap(); }
    internal int Poll(uint now)
    {
        for (int i = 0; i < Profiles.Length; i++) if (Profiles[i].Binding.Enabled && Profiles[i].State.Poll(now)) return i;
        return -1;
    }
    internal GestureResult Handle(Native.KBDLLHOOKSTRUCT key, bool down, KeySnapshot keys)
    {
        var result = new GestureResult { Profile = -1 };
        for (int i = 0; i < Profiles.Length; i++)
        {
            RuntimeProfile p = Profiles[i];
            if (!p.Binding.Enabled) continue;
            bool activation = p.State.IsActivation((int)key.vkCode);
            if (!activation && ((p.State.DialActive && p.Binding.DoubleHoldMode == "Hold a key") || (p.State.OrdinaryHeld && p.Binding.HoldMode == "Hold a key"))) continue;
            int otherModifiers = keys.ModifierFlags & ~KeyChord.FamilyFlag(p.State.Family);
            bool alone = otherModifiers == 0 && !keys.MouseHeld;
            if (p.State.IsActivation((int)key.vkCode)) alone = alone && !keys.OtherKeysExcept(p.State.Family);
            GestureAction action = p.State.InputEvent(key, down, alone);
            if (activation && down && p.Binding.HoldMode != "Dial modifier") action |= GestureAction.Consume;
            if (action != GestureAction.None)
            {
                if (result.Profile >= 0 && result.Profile != i) { Reset(); return new GestureResult { Profile = -1 }; }
                result.Action = action; result.Profile = i;
            }
        }
        return result;
    }
    internal static void SelfTest()
    {
        // Exercise the combined event router and cached key state, rather than
        // only testing the three recognizers separately.
        for (int profile = 0; profile < 3; profile++)
        {
            AppSettings defaults = AppSettings.Defaults();
            var router = new GestureBank(defaults); var snapshot = new KeySnapshot();
            int vk = profile == 0 ? 0xA4 : profile == 1 ? 0xA2 : 0xA0;
            Route(router, snapshot, vk, true, 100);
            GestureResult up = Route(router, snapshot, vk, false, 180);
            if (up.Profile != profile || (up.Action & GestureAction.ReleaseModifier) == 0 || router.Poll(280) != profile)
                throw new Exception("Combined modifier tap routing.");
            router.Reset(); snapshot.Clear();
            Route(router, snapshot, vk, true, 100); Route(router, snapshot, vk, false, 180); Route(router, snapshot, vk, true, 250);
            GestureResult next = Route(router, snapshot, 0xDD, true, 300);
            if (router.DialOwner != profile || next.Profile != profile || (next.Action & GestureAction.Next) == 0)
                throw new Exception("Combined modifier cycling routing.");
            Route(router, snapshot, 0xDD, false, 310); Route(router, snapshot, vk, false, 900);
            if (router.DialOwner != -1 || router.Poll(1100) != -1) throw new Exception("Combined router release.");
            defaults.Modifiers[profile].Enabled = false; router.Configure(defaults); snapshot.Clear();
            if (Route(router, snapshot, vk, true, 100).Action != GestureAction.None
                || Route(router, snapshot, vk, false, 180).Action != GestureAction.None || router.Poll(400) != -1)
                throw new Exception("Individual modifier disable.");
        }
        var nativeRouter = new GestureBank(AppSettings.Defaults()); var nativeKeys = new KeySnapshot();
        Route(nativeRouter, nativeKeys, 0xA2, true, 100); Route(nativeRouter, nativeKeys, 0xA0, true, 120);
        if (Route(nativeRouter, nativeKeys, 0x43, true, 150).Action != GestureAction.None) throw new Exception("Native Ctrl+Shift+C intercepted.");
        Route(nativeRouter, nativeKeys, 0x43, false, 170); Route(nativeRouter, nativeKeys, 0xA0, false, 190); Route(nativeRouter, nativeKeys, 0xA2, false, 200);
        if (nativeRouter.Poll(400) != -1) throw new Exception("Native multi-modifier shortcut generated output.");
        foreach (int family in new int[] { 0x12, 0x11, 0x10 })
        {
            int vk = family == 0x12 ? 0xA4 : family == 0x11 ? 0xA2 : 0xA0;
            var g = new ModifierGestures(family);
            if (g.KeyEvent(vk, true, 100, true) != GestureAction.None || g.KeyEvent(vk, false, 900, true) != GestureAction.None)
                throw new Exception("Ordinary modifier hold altered.");
            g.Reset(); g.KeyEvent(vk, true, 100, true); g.KeyEvent(vk, false, 180, true);
            if (g.Poll(279) || !g.Poll(280)) throw new Exception("Modifier tap timing.");
            g.Reset(); g.KeyEvent(vk, true, 100, true); g.KeyEvent(vk, false, 180, true); g.KeyEvent(vk, true, 250, true);
            if (!g.DialActive || (g.KeyEvent(0xDD, true, 300, true) & GestureAction.Next) == 0) throw new Exception("Modifier tap-hold cycling.");
            g.KeyEvent(vk, false, 900, true);
            if (g.DialActive || g.Poll(1200)) throw new Exception("Modifier cycle release.");
            g.Reset(); g.KeyEvent(vk, true, 100, true); g.KeyEvent(0x43, true, 130, true); g.KeyEvent(vk, false, 180, true);
            if (g.Poll(400)) throw new Exception("Native shortcut generated stray tap.");
        }
        foreach (string mode in new string[] { "No action", "Dial modifier", "Cycle list", "Dial scrolling", "Hold a key" })
        {
            var settings = AppSettings.Defaults(); settings.Modifiers[1].DoubleHoldMode = mode;
            var router = new GestureBank(settings); var snapshot = new KeySnapshot();
            Route(router, snapshot, 0xA2, true, 100); Route(router, snapshot, 0xA2, false, 160); Route(router, snapshot, 0xA2, true, 220);
            GestureResult notch = Route(router, snapshot, 0xDD, true, 240);
            if (mode == "Hold a key" ? notch.Action != GestureAction.None : (notch.Action & GestureAction.Next) == 0)
                throw new Exception("Tap-hold action routing: " + mode);
            Route(router, snapshot, 0xDD, false, 250); Route(router, snapshot, 0xA2, false, 900);
            if (router.DialOwner != -1) throw new Exception("Tap-hold action release.");
        }
        foreach (string mode in new string[] { "No action", "Dial modifier", "Cycle list", "Dial scrolling", "Hold a key" })
        {
            var settings = AppSettings.Defaults(); settings.Modifiers[2].HoldMode = mode;
            var router = new GestureBank(settings); var snapshot = new KeySnapshot();
            GestureResult press = Route(router, snapshot, 0xA0, true, 100);
            if (((press.Action & GestureAction.Consume) != 0) != (mode != "Dial modifier")) throw new Exception("Ordinary modifier passthrough/override.");
            if (router.Profiles[2].State.HoldReady(400) || !router.Profiles[2].State.HoldReady(401)) throw new Exception("Ordinary hold threshold.");
            GestureResult notch = Route(router, snapshot, 0xDD, true, 450);
            if (mode == "Hold a key" ? notch.Action != GestureAction.None : (notch.Action & GestureAction.HoldForward) == 0) throw new Exception("Ordinary action routing.");
            Route(router, snapshot, 0xDD, false, 460); Route(router, snapshot, 0xA0, false, 900);
            if (router.Profiles[2].State.OrdinaryHeld || router.Poll(1100) != -1) throw new Exception("Ordinary action release/tap leakage.");
        }
        var timerSettings = AppSettings.Defaults(); var timerBank = new GestureBank(timerSettings); var timerKeys = new KeySnapshot();
        if (timerBank.NeedsTimer(-1)) throw new Exception("Idle gestures requested polling.");
        Route(timerBank, timerKeys, 0xA2, true, 100); Route(timerBank, timerKeys, 0xA2, false, 150);
        if (!timerBank.NeedsTimer(-1)) throw new Exception("Pending tap did not request a timer.");
        timerBank.Poll(250); if (timerBank.NeedsTimer(-1)) throw new Exception("Completed tap kept polling.");
        timerSettings.Modifiers[1].HoldMode = "Hold a key"; timerBank.Configure(timerSettings); timerKeys.Clear();
        Route(timerBank, timerKeys, 0xA2, true, 100);
        if (!timerBank.NeedsTimer(-1) || timerBank.NeedsTimer(1)) throw new Exception("Held-key timer lifecycle.");
        for (int profile = 0; profile < 3; profile++)
        {
            var settings = AppSettings.Defaults(); settings.Modifiers[profile].HoldMode = "Dial scrolling";
            var router = new GestureBank(settings); var snapshot = new KeySnapshot();
            int key = profile == 0 ? 0xA4 : profile == 1 ? 0xA2 : 0xA0;
            Native.KBDLLHOOKSTRUCT wrappedEvent = new Native.KBDLLHOOKSTRUCT { vkCode = (uint)key, flags = 0x10, time = 100 };
            bool captured = router.Captured(key); router.Handle(wrappedEvent, true, snapshot); if (!(captured && router.Captured(key))) snapshot.Set(key, true);
            for (int notch = 0; notch < 1000; notch++)
            {
                int[] packet = { key, 0xDD, 0xDD, key }; bool[] edges = { true, true, false, false };
                for (int e = 0; e < packet.Length; e++)
                {
                    wrappedEvent.vkCode = (uint)packet[e]; wrappedEvent.time++;
                    captured = router.Captured(packet[e]); GestureResult result = router.Handle(wrappedEvent, edges[e], snapshot);
                    if (!(captured && router.Captured(packet[e]))) snapshot.Set(packet[e], edges[e]);
                    if (e == 1 && (result.Action & GestureAction.HoldForward) == 0) throw new Exception("Lost wrapped ordinary scrolling notch.");
                }
                if (!snapshot.IsDown(key) || !router.Profiles[profile].State.OrdinaryHeld) throw new Exception("Nested modifier packet ended the held gesture.");
            }
            wrappedEvent.vkCode = (uint)key; wrappedEvent.time++; router.Handle(wrappedEvent, false, snapshot);
            if (router.Profiles[profile].State.OrdinaryHeld) throw new Exception("Wrapped ordinary scrolling release.");
        }
        AppSettings s = AppSettings.Defaults();
        foreach (ModifierBinding p in s.Modifiers) p.Enabled = false;
        var bank = new GestureBank(s); var keys = new KeySnapshot();
        var input = new Native.KBDLLHOOKSTRUCT { vkCode = 0xA2, time = 100 };
        if (bank.Handle(input, true, keys).Action != GestureAction.None) throw new Exception("Disabled modifier intercepted.");
        input.time = 180; bank.Handle(input, false, keys);
        if (bank.Poll(400) != -1) throw new Exception("Disabled modifier output.");
        var custom = new ModifierGestures(0x11, 0x26, 0x28, 150, 250);
        custom.KeyEvent(0xA2, true, 100, true);
        if ((custom.KeyEvent(0x26, true, 150, true) & GestureAction.HoldForward) == 0) throw new Exception("Configured input key.");
    }
    private static GestureResult Route(GestureBank router, KeySnapshot keys, int key, bool down, uint time)
    {
        bool captured = router.Captured(key);
        GestureResult result = router.Handle(new Native.KBDLLHOOKSTRUCT { vkCode = (uint)key, time = time }, down, keys);
        if (!(captured && router.Captured(key))) keys.Set(key, down);
        return result;
    }
}

internal static class InputBuilder
{
    internal static Native.INPUT[] DialScroll(ModifierBinding binding, int direction)
    {
        int family = KeyChord.ModifierKey(binding.Modifier);
        ushort first = family == 0x12 ? (ushort)0xA4 : family == 0x11 ? (ushort)0xA2 : (ushort)0xA0;
        // The controller's activation modifier must not turn wheel input into
        // Ctrl+wheel zoom or Shift+wheel horizontal scrolling.
        return WithHeld(ScrollOutput(binding, direction), new ushort[] { first, (ushort)(first + 1) }, false);
    }
    internal static KeyChord ScrollOutput(ModifierBinding binding, int direction)
    { if (binding.ReverseScroll) direction = -direction; return new KeyChord { Key = direction > 0 ? KeyChord.WheelUp : KeyChord.WheelDown, WheelNotches = binding.ScrollAmount }; }
    internal static int OutputModifiers(KeyChord chord)
    {
        int flags = chord.Modifiers;
        foreach (int family in new int[] { 0x12, 0x11, 0x10 })
            if (KeyChord.InFamily(chord.Key, family)) flags |= KeyChord.FamilyFlag(family);
        if (chord.Key == 0x5B || chord.Key == 0x5C) flags |= KeyChord.Win;
        return flags;
    }
    internal static Native.INPUT[] Hold(KeyChord chord, bool release)
    {
        var keys = new List<ushort>();
        if ((chord.Modifiers & KeyChord.Control) != 0) keys.Add(0xA2);
        if ((chord.Modifiers & KeyChord.Alt) != 0) keys.Add(0xA4);
        if ((chord.Modifiers & KeyChord.Shift) != 0) keys.Add(0xA0);
        if ((chord.Modifiers & KeyChord.Win) != 0) keys.Add(0x5B);
        if (!keys.Contains(chord.Key)) keys.Add(chord.Key);
        if (release) keys.Reverse();
        var input = new List<Native.INPUT>(); foreach (ushort key in keys) input.Add(Key(key, release));
        return input.ToArray();
    }
    internal static Native.INPUT Key(ushort key, bool up)
    {
        var input = new Native.INPUT(); input.type = 1;
        input.data.ki.wVk = key; input.data.ki.dwFlags = up ? 2u : 0u;
        if ((key >= 0x21 && key <= 0x28) || key == 0x2C || key == 0x2D || key == 0x2E
            || key == 0xA3 || key == 0xA5 || key == 0x5B || key == 0x5C || key == 0x6F || key == 0x90)
            input.data.ki.dwFlags |= 1;
        input.data.ki.dwExtraInfo = new UIntPtr(ModifierGestures.OwnInputMarker);
        return input;
    }
    private static void AppendChord(List<Native.INPUT> input, KeyChord chord)
    {
        if (chord.IsNone) return;
        ushort[] modifiers = { 0xA2, 0xA4, 0xA0, 0x5B };
        int[] flags = { KeyChord.Control, KeyChord.Alt, KeyChord.Shift, KeyChord.Win };
        for (int i = 0; i < 4; i++) if ((chord.Modifiers & flags[i]) != 0) input.Add(Key(modifiers[i], false));
        if (chord.IsWheel)
        {
            var wheel = new Native.INPUT(); wheel.type = 0;
            wheel.data.mi.dwFlags = 0x0800;
            wheel.data.mi.mouseData = unchecked((uint)((chord.Key == KeyChord.WheelUp ? 120 : -120) * chord.WheelNotches));
            wheel.data.mi.dwExtraInfo = new UIntPtr(ModifierGestures.OwnInputMarker);
            input.Add(wheel);
        }
        else { input.Add(Key(chord.Key, false)); input.Add(Key(chord.Key, true)); }
        for (int i = 3; i >= 0; i--) if ((chord.Modifiers & flags[i]) != 0) input.Add(Key(modifiers[i], true));
    }
    internal static Native.INPUT[] Build(KeyChord chord)
    { var input = new List<Native.INPUT>(); AppendChord(input, chord); return input.ToArray(); }
    internal static Native.INPUT[] WithHeld(KeyChord chord, ushort[] held, bool restore)
    {
        if (chord.IsNone) return new Native.INPUT[0];
        var input = new List<Native.INPUT>();
        bool mask = false, ctrl = false;
        foreach (ushort key in held)
        {
            if (key == 0xA4 || key == 0xA5 || key == 0x5B || key == 0x5C) mask = true;
            if (key == 0xA2 || key == 0xA3) ctrl = true;
        }
        mask = mask && !ctrl;
        if (mask) input.Add(Key(0xA2, false));
        foreach (ushort key in held) input.Add(Key(key, true));
        if (mask) input.Add(Key(0xA2, true));
        AppendChord(input, chord);
        if (restore) foreach (ushort key in held) input.Add(Key(key, false));
        return input.ToArray();
    }
    internal static ushort[] HeldModifiers()
    {
        var result = new List<ushort>();
        // Release Alt/Win first while any held Ctrl can still mask their menus.
        foreach (ushort key in new ushort[] { 0xA4, 0xA5, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3 })
            if ((Native.GetAsyncKeyState(key) & 0x8000) != 0) result.Add(key);
        return result.ToArray();
    }
    internal static void SelfTest()
    {
        foreach (string name in new string[] { "Alt", "Ctrl", "Shift" })
        {
            ModifierBinding binding = AppSettings.Defaults().Modifiers.Find(delegate(ModifierBinding p) { return p.Modifier == name; });
            foreach (int direction in new int[] { -1, 1 })
            {
                var down = new HashSet<ushort>();
                int family = KeyChord.ModifierKey(name); ushort first = family == 0x12 ? (ushort)0xA4 : family == 0x11 ? (ushort)0xA2 : (ushort)0xA0;
                down.Add(first); down.Add((ushort)(first + 1)); int wheels = 0;
                foreach (Native.INPUT input in DialScroll(binding, direction))
                {
                    if (input.type == 0)
                    { if (down.Count != 0 || input.data.mi.mouseData != (direction > 0 ? 120u : unchecked((uint)-120))) throw new Exception("Wheel carried an activation modifier."); wheels++; }
                    else if ((input.data.ki.dwFlags & 2) != 0) down.Remove(input.data.ki.wVk); else down.Add(input.data.ki.wVk);
                }
                if (wheels != 1 || down.Count != 0) throw new Exception("Wheel envelope imbalance.");
            }
        }
        KeyChord none = KeyChord.Parse("No action");
        if (!none.IsNone || Build(none).Length != 0 || WithHeld(none, new ushort[] { 0xA4, 0xA2 }, true).Length != 0)
            throw new Exception("No action emitted input.");
        var scroll = AppSettings.Defaults().Modifiers[0]; scroll.ReverseScroll = true; scroll.ScrollAmount = 3;
        Native.INPUT[] scrollInputs = Build(ScrollOutput(scroll, 1));
        if (scrollInputs.Length != 1 || scrollInputs[0].data.mi.mouseData != unchecked((uint)-360)) throw new Exception("Scroll reversal/amount.");
        foreach (string text in new string[] { "Space", "Ctrl", "Alt", "Shift", "Win", "Ctrl+Shift+F1" })
        {
            KeyChord hold = KeyChord.ParseHold(text), copy = KeyChord.ParseHold(KeyChord.ParseHold(text).ToString());
            if (text == "Ctrl" && OutputModifiers(hold) != KeyChord.Control) throw new Exception("Held modifier shortcut tracking.");
            if (hold.Key != copy.Key || hold.Modifiers != copy.Modifiers) throw new Exception("Held output round-trip.");
            var held = new HashSet<ushort>();
            foreach (Native.INPUT item in Hold(hold, false))
            { if (item.type != 1 || item.data.ki.dwFlags == 2 || !held.Add(item.data.ki.wVk)) throw new Exception("Held output down edges."); }
            foreach (Native.INPUT item in Hold(hold, true))
            { if ((item.data.ki.dwFlags & 2) == 0 || !held.Remove(item.data.ki.wVk)) throw new Exception("Held output up edges."); }
            if (held.Count != 0) throw new Exception("Held output stuck keys.");
        }
        if (Marshal.SizeOf(typeof(Native.INPUT)) != (IntPtr.Size == 8 ? 40 : 28)) throw new Exception("Native INPUT size.");
        foreach (string text in new string[] { "B", "Ctrl+Shift+F1", "Alt+Tab", "Win+Left", "Scroll up", "Scroll down", "Ctrl+WheelUp" })
        {
            KeyChord chord = KeyChord.Parse(text);
            foreach (bool restore in new bool[] { false, true })
            {
                ushort[] held = { 0xA4, 0xA0, 0xA2 };
                var down = new HashSet<ushort>(held);
                int wheels = 0;
                foreach (Native.INPUT input in WithHeld(chord, held, restore))
                {
                    if (input.type == 0)
                    {
                        if (!chord.IsWheel || input.data.mi.dwFlags != 0x0800 || input.data.mi.mouseData != (chord.Key == KeyChord.WheelUp ? 120u : unchecked((uint)-120))
                            || input.data.mi.dwExtraInfo.ToUInt64() != ModifierGestures.OwnInputMarker) throw new Exception("Wheel output flags/direction/tagging.");
                        wheels++; continue;
                    }
                    if (input.type != 1 || input.data.ki.dwExtraInfo.ToUInt64() != ModifierGestures.OwnInputMarker) throw new Exception("Output tagging.");
                    if ((input.data.ki.dwFlags & 2) != 0) down.Remove(input.data.ki.wVk); else down.Add(input.data.ki.wVk);
                }
                if (restore ? !down.SetEquals(held) : down.Count != 0) throw new Exception("Output modifier restoration.");
                if (wheels != (chord.IsWheel ? 1 : 0)) throw new Exception("Wheel notch count.");
            }
        }
    }
}

