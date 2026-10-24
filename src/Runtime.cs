using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

internal sealed class RuntimeProfile
{
    internal ModifierBinding Binding;
    internal ModifierGestures State;
    internal KeyChord Tap, Forward, Backward;
}

internal struct GestureResult
{
    internal GestureAction Action;
    internal int Profile;
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
                Backward = KeyChord.Parse(p.HoldPreviousOutput), State = new ModifierGestures(KeyChord.ModifierKey(p.Modifier),
                    KeyChord.Parse(p.NextInput).Key, KeyChord.Parse(p.PreviousInput).Key, (uint)p.TapWaitMs, (uint)p.ShortPressMs) });
        Profiles = list.ToArray();
    }
    internal int DialOwner
    {
        get { for (int i = 0; i < Profiles.Length; i++) if (Profiles[i].Binding.Enabled && Profiles[i].State.DialActive) return i; return -1; }
    }
    internal bool Captured(int key)
    {
        int owner = DialOwner;
        return owner >= 0 && Profiles[owner].State.IsActivation(key);
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
            int otherModifiers = keys.ModifierFlags & ~KeyChord.FamilyFlag(p.State.Family);
            bool alone = otherModifiers == 0 && !keys.MouseHeld;
            if (p.State.IsActivation((int)key.vkCode)) alone = alone && !keys.OtherKeysExcept(p.State.Family);
            GestureAction action = p.State.InputEvent(key, down, alone);
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
        ushort[] modifiers = { 0xA2, 0xA4, 0xA0, 0x5B };
        int[] flags = { KeyChord.Control, KeyChord.Alt, KeyChord.Shift, KeyChord.Win };
        for (int i = 0; i < 4; i++) if ((chord.Modifiers & flags[i]) != 0) input.Add(Key(modifiers[i], false));
        input.Add(Key(chord.Key, false)); input.Add(Key(chord.Key, true));
        for (int i = 3; i >= 0; i--) if ((chord.Modifiers & flags[i]) != 0) input.Add(Key(modifiers[i], true));
    }
    internal static Native.INPUT[] Build(KeyChord chord)
    { var input = new List<Native.INPUT>(); AppendChord(input, chord); return input.ToArray(); }
    internal static Native.INPUT[] WithHeld(KeyChord chord, ushort[] held, bool restore)
    {
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
        if (Marshal.SizeOf(typeof(Native.INPUT)) != (IntPtr.Size == 8 ? 40 : 28)) throw new Exception("Native INPUT size.");
        foreach (string text in new string[] { "B", "Ctrl+Shift+F1", "Alt+Tab", "Win+Left" })
        {
            KeyChord chord = KeyChord.Parse(text);
            foreach (bool restore in new bool[] { false, true })
            {
                ushort[] held = { 0xA4, 0xA0, 0xA2 };
                var down = new HashSet<ushort>(held);
                foreach (Native.INPUT input in WithHeld(chord, held, restore))
                {
                    if (input.type != 1 || input.data.ki.dwExtraInfo.ToUInt64() != ModifierGestures.OwnInputMarker) throw new Exception("Output tagging.");
                    if ((input.data.ki.dwFlags & 2) != 0) down.Remove(input.data.ki.wVk); else down.Add(input.data.ki.wVk);
                }
                if (restore ? !down.SetEquals(held) : down.Count != 0) throw new Exception("Output modifier restoration.");
            }
        }
    }
}

