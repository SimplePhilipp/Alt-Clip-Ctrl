// Alt Clip Ctrl: standalone Windows gesture helper for Clip Studio Paint.
// No network, keyboard log, startup registration, or AutoHotkey dependency.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using System.Diagnostics;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        bool test = args.Length == 2 && args[0] == "--self-test";
        bool smoke = args.Length == 2 && args[0] == "--smoke-test";
        try
        {
            if (test)
            {
                MainForm.SelfTest();
                File.WriteAllText(args[1], "PASS: 60000 scroll-session turns, exact direction/order, one steady wheel event per turn, session reset, cached output and gesture regressions.\r\n");
                return 0;
            }
            bool first;
            // Retain the original mutex so older helper versions cannot overlap.
            using (var instance = new Mutex(true, "Local\\CSPToolCyclerStandalone" + (smoke ? "SmokeTest" : ""), out first))
            {
                if (!first) { MessageBox.Show("Alt Clip Ctrl or an earlier helper is already running. Exit it from its tray menu first.", "Alt Clip Ctrl"); return 0; }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                if (smoke) Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
                using (var form = new MainForm(smoke))
                {
                    if (smoke)
                    {
                        var timer = new System.Windows.Forms.Timer { Interval = 350 };
                        timer.Tick += delegate {
                            timer.Stop(); form.VerifyConfigUi(args[1]);
                            File.WriteAllText(args[1], "PASS: 12000 immediate-dispatch/overlapping-notch checks without UI pumping, plain-language UI, idle timer, held-output cleanup and shutdown.\r\n");
                            timer.Dispose(); form.Close();
                            if (!form.IsDisposed) throw new Exception("Closing the main window did not exit.");
                            form.VerifyReleasedOutputs();
                        };
                        timer.Start();
                    }
                    Application.Run(form);
                }
            }
            return 0;
        }
        catch (Exception ex)
        {
            if (test || smoke) File.WriteAllText(args[1], "FAIL: " + ex.ToString());
            else MessageBox.Show(ex.Message, "Alt Clip Ctrl", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}

internal sealed class MainForm : Form
{
    private readonly bool testMode;
    private readonly uint ownProcess = (uint)Process.GetCurrentProcess().Id;
    private readonly string settingsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "AltClipCtrl.settings.xml");
    private AppSettings config;
    private GestureBank gestures;
    private ToolCycle[] cycles;
    private readonly ScrollSession scrollSession = new ScrollSession();
    private readonly KeySnapshot keys = new KeySnapshot();
    private readonly Label summary = new Label(), status = new Label(), tracked = new Label();
    private readonly NotifyIcon tray = new NotifyIcon();
    private readonly ContextMenuStrip trayMenu = new ContextMenuStrip();
    private readonly System.Windows.Forms.Timer scopeClock = new System.Windows.Forms.Timer();
    private readonly System.Windows.Forms.Timer gestureClock = new System.Windows.Forms.Timer();
    private Native.WinEventProc foregroundCallback;
    private Native.InputHookProc keyboardCallback, mouseCallback;
    private IntPtr foregroundHook, keyboardHook, mouseHook, activeWindow;
    private bool paused, uiDirty;
    private uint lastUi;
    private uint checkedProcess;
    private bool checkedIsCsp;
    private KeyChord heldOutput;
    private readonly List<Native.INPUT> diagnosticInputs = new List<Native.INPUT>();
    private int heldProfile = -1;
    private bool heldIsDouble;
    private const int HoldStateMessage = 0x8006;
    private const int ReleaseMessage = 0x8001, TrackMessage = 0x8002, CycleMessage = 0x8003, OutputMessage = 0x8005;

    internal MainForm(bool diagnostic)
    {
        testMode = diagnostic;
        config = AppSettings.Defaults();
        if (!testMode && File.Exists(settingsPath))
        {
            try { config = AppSettings.Load(settingsPath); }
            catch (Exception ex) { MessageBox.Show("Settings could not be loaded; defaults will be used.\r\n" + ex.Message, "Alt Clip Ctrl"); }
        }
        Text = "Alt Clip Ctrl";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        Font = new Font("Segoe UI", 10);
        ClientSize = new Size(600, 390);
        FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        summary.SetBounds(22, 20, 556, 55);
        status.SetBounds(22, 84, 556, 44);
        tracked.SetBounds(22, 126, 556, 50); tracked.AutoEllipsis = true;
        var explanation = new Label {
            Text = "Direct tool shortcuts keep tracking in sync. After choosing a tool\r\nwith the mouse, press its configured shortcut to resync.",
            Location = new Point(22, 171), Size = new Size(556, 48)
        };
        var notation = new Label {
            Text = "Tap: press and release. Hold: keep the button pressed.\r\nTap then hold: tap, release, then press and keep holding.\r\nChoose each gesture's action in Config.",
            Location = new Point(22, 226), Size = new Size(556, 77)
        };
        var configure = new Button { Text = "Config", Location = new Point(22, 327), Size = new Size(160, 38) };
        configure.Click += delegate { OpenConfig(); };
        Controls.AddRange(new Control[] { summary, status, tracked, explanation, notation, configure });
        trayMenu.Items.Add("Open Alt Clip Ctrl", null, delegate { ShowControls(); });
        trayMenu.Items.Add("Config", null, delegate { OpenConfig(); });
        trayMenu.Items.Add("Forget all cycle positions", null, delegate { ResetPositions(); UpdateUi(); });
        var pause = new ToolStripMenuItem("Pause") { CheckOnClick = true };
        pause.CheckedChanged += delegate { paused = pause.Checked; RefreshScope(); };
        trayMenu.Items.Add(pause); trayMenu.Items.Add("Exit", null, delegate { Quit(); });
        tray.Icon = Icon; tray.ContextMenuStrip = trayMenu; tray.DoubleClick += delegate { ShowControls(); }; tray.Visible = true;
        ApplyConfig(config);
        scopeClock.Interval = 1000; scopeClock.Tick += delegate { RefreshScope(); };
        gestureClock.Interval = 15;
        gestureClock.Tick += delegate {
            if (activeWindow == IntPtr.Zero || paused || testMode || Native.GetForegroundWindow() != activeWindow) { EndCustomHold(); scrollSession.Reset(); gestures.Reset(); gestureClock.Stop(); return; }
            uint now = Native.GetTickCount();
            for (int i = 0; i < gestures.Profiles.Length; i++)
            {
                RuntimeProfile p = gestures.Profiles[i];
                if (p.Binding.Enabled && p.Binding.HoldMode == "Hold a key" && p.State.HoldReady(now) && heldOutput == null)
                { p.State.CancelTap(); BeginCustomHold(i, false); }
            }
            int tap = gestures.Poll(now);
            if (tap >= 0) SendOutput(tap, gestures.Profiles[tap].Tap, false, true, gestures.Profiles[tap].TapInputs);
            if (uiDirty && unchecked(now - lastUi) >= 40) { UpdateUi(); lastUi = now; }
            UpdateGestureTimer();
        };
    }

    private void ApplyConfig(AppSettings value)
    {
        EndCustomHold(); scrollSession.Reset(); value.Validate(); config = value; gestures = new GestureBank(config);
        cycles = new ToolCycle[config.Modifiers.Count];
        for (int i = 0; i < cycles.Length; i++) cycles[i] = new ToolCycle(config.Modifiers[i].Tools);
        string enabled = "";
        foreach (ModifierBinding p in config.Modifiers) if (p.Enabled) enabled += (enabled.Length == 0 ? "" : ", ") + p.Modifier;
        summary.Text = "Enabled profiles: " + (enabled.Length == 0 ? "none" : enabled) + "\r\nOpen Config to change inputs, outputs, timings, or enable switches.";
        UpdateUi();
    }
    private void OpenConfig()
    {
        ShowControls();
        using (var dialog = new ConfigForm(config))
        {
            if (dialog.ShowDialog(this) != DialogResult.OK) return;
            try { dialog.Result.Save(settingsPath); ApplyConfig(dialog.Result); RefreshScope(); }
            catch (Exception ex) { MessageBox.Show("Could not save config. Keep the app in a writable folder.\r\n" + ex.Message, "Alt Clip Ctrl"); }
        }
    }
    private void ShowControls() { UpdateUi(); Show(); WindowState = FormWindowState.Normal; Activate(); }
    private void Quit() { Close(); }
    private void UpdateUi()
    {
        uiDirty = false;
        string names = "";
        for (int i = 0; i < cycles.Length; i++) names += (i == 0 ? "" : i == 2 ? "\r\n" : "   |   ") + config.Modifiers[i].Modifier + ": " + cycles[i].Name;
        tracked.Text = names;
        string trayText = "Alt Clip Ctrl: " + names.Replace("\r\n", " | ");
        tray.Text = trayText.Length > 63 ? trayText.Substring(0, 60) + "..." : trayText;
        int owner = gestures.DialOwner;
        status.Text = paused ? "Paused from the tray menu." : !config.Enabled ? "Disabled in Config." : activeWindow == IntPtr.Zero ?
            (config.DetectClipStudio ? "Waiting for Clip Studio Paint to become active." : "Controls excluded; switch to another app to use bindings.") : owner >= 0 ?
            "Tap then hold " + gestures.Profiles[owner].Binding.Modifier + ": " + gestures.Profiles[owner].Binding.DoubleHoldMode + ". Release to exit." :
            (config.DetectClipStudio ? "Ready in Clip Studio Paint." : "Ready in this app. CSP auto-detection is off.");
    }
    protected override void OnLoad(EventArgs e)
    {
        base.OnLoad(e);
        foregroundCallback = delegate(IntPtr h, uint ev, IntPtr w, int obj, int child, uint thread, uint time) { if (!IsDisposed && !Disposing) RefreshScope(); };
        foregroundHook = Native.SetWinEventHook(3, 3, IntPtr.Zero, foregroundCallback, 0, 0, 0);
        if (foregroundHook == IntPtr.Zero) throw new InvalidOperationException("Could not enable foreground notifications.");
        RefreshScope(); scopeClock.Start();
        if (testMode) { if (!EnableHooks()) throw new InvalidOperationException("Listener setup failed."); DisableHooks(); Hide(); }
    }
    private bool CspIsForeground()
    {
        uint pid; Native.GetWindowThreadProcessId(Native.GetForegroundWindow(), out pid);
        if (pid == 0) return false;
        if (pid == checkedProcess) return checkedIsCsp;
        checkedProcess = pid; checkedIsCsp = false;
        try { using (Process p = Process.GetProcessById((int)pid)) { checkedIsCsp = string.Equals(p.ProcessName, "CLIPStudioPaint", StringComparison.OrdinalIgnoreCase); return checkedIsCsp; } }
        catch (ArgumentException) { return false; } catch (System.ComponentModel.Win32Exception) { return false; } catch (InvalidOperationException) { return false; }
    }
    private void RefreshScope()
    {
        if (IsDisposed || Disposing || !IsHandleCreated) return;
        if (paused || testMode || !config.Enabled || !TargetAllowed()) { activeWindow = IntPtr.Zero; DisableHooks(); UpdateUi(); return; }
        IntPtr current = Native.GetForegroundWindow();
        if (activeWindow == current && keyboardHook != IntPtr.Zero && mouseHook != IntPtr.Zero) return;
        if (activeWindow != current) { EndCustomHold(); scrollSession.Reset(); gestures.Reset(); if (keyboardHook != IntPtr.Zero) SeedKeys(); }
        activeWindow = current;
        if (!EnableHooks()) status.Text = "Input listeners unavailable. Restart the app."; else UpdateUi();
        UpdateGestureTimer();
    }
    private bool TargetAllowed()
    {
        if (config.DetectClipStudio) return CspIsForeground();
        uint process; Native.GetWindowThreadProcessId(Native.GetForegroundWindow(), out process);
        return process != 0 && process != ownProcess;
    }
    private bool EnableHooks()
    {
        if (keyboardHook != IntPtr.Zero && mouseHook != IntPtr.Zero) return true;
        keyboardCallback = KeyboardEvent; mouseCallback = MouseEvent;
        IntPtr module = Native.GetModuleHandle(null);
        keyboardHook = Native.SetWindowsHookEx(13, keyboardCallback, module, 0); mouseHook = Native.SetWindowsHookEx(14, mouseCallback, module, 0);
        if (keyboardHook != IntPtr.Zero && mouseHook != IntPtr.Zero) { SeedKeys(); return true; }
        DisableHooks(); return false;
    }
    private void DisableHooks()
    {
        gestureClock.Stop();
        scrollSession.Reset();
        EndCustomHold();
        if (keyboardHook != IntPtr.Zero) Native.UnhookWindowsHookEx(keyboardHook);
        if (mouseHook != IntPtr.Zero) Native.UnhookWindowsHookEx(mouseHook);
        keyboardHook = mouseHook = IntPtr.Zero; gestures.Reset(); keys.Clear();
    }
    private void SeedKeys()
    {
        keys.Clear();
        for (int vk = 1; vk <= 0xFE; vk++) if (vk != 0x10 && vk != 0x11 && vk != 0x12) keys.Set(vk, (Native.GetAsyncKeyState(vk) & 0x8000) != 0);
    }
    private IntPtr KeyboardEvent(int code, IntPtr message, IntPtr data)
    {
        if (code < 0) return Native.CallNextHookEx(keyboardHook, code, message, data);
        Native.KBDLLHOOKSTRUCT key = (Native.KBDLLHOOKSTRUCT)Marshal.PtrToStructure(data, typeof(Native.KBDLLHOOKSTRUCT));
        if (key.dwExtraInfo.ToUInt64() == ModifierGestures.OwnInputMarker) return Native.CallNextHookEx(keyboardHook, code, message, data);
        if (activeWindow == IntPtr.Zero || Native.GetForegroundWindow() != activeWindow || paused) { EndCustomHold(); scrollSession.Reset(); gestures.Reset(); return Native.CallNextHookEx(keyboardHook, code, message, data); }
        key.vkCode = (uint)KeySnapshot.Normalize((int)key.vkCode, key.flags, key.scanCode);
        int msg = message.ToInt32(); bool down = msg == 0x100 || msg == 0x104, up = msg == 0x101 || msg == 0x105;
        if (!down && !up) return Native.CallNextHookEx(keyboardHook, code, message, data);
        int ownerBefore = gestures.DialOwner;
        bool capturedBefore = gestures.Captured((int)key.vkCode);
        int modifiers = keys.ModifierFlags;
        if (ownerBefore >= 0) modifiers &= ~KeyChord.FamilyFlag(gestures.Profiles[ownerBefore].State.Family);
        foreach (RuntimeProfile p in gestures.Profiles)
            if (p.Binding.Enabled && p.Binding.HoldMode != "Dial modifier" && p.State.OrdinaryHeld)
                modifiers &= ~KeyChord.FamilyFlag(p.State.Family);
        if (heldOutput != null) modifiers |= InputBuilder.OutputModifiers(heldOutput);
        GestureResult result = gestures.Handle(key, down, keys);
        scrollSession.Sync(gestures.Profiles);
        if (down && (result.Action & GestureAction.Consume) == 0)
        {
            for (int p = 0; p < cycles.Length; p++)
            {
                int index = cycles[p].Index((int)key.vkCode, modifiers);
                if (index >= 0) Native.PostMessage(Handle, TrackMessage, new IntPtr(p * 64 + index), activeWindow);
            }
        }
        if (!(capturedBefore && gestures.Captured((int)key.vkCode))) keys.Set((int)key.vkCode, down);
        if ((result.Action & GestureAction.ReleaseModifier) != 0)
            if (!Native.PostMessage(Handle, ReleaseMessage, new IntPtr(key.vkCode), activeWindow)) { scrollSession.Reset(); gestures.Reset(); return Native.CallNextHookEx(keyboardHook, code, message, data); }
        if (!DispatchScroll(result))
        {
            if ((result.Action & GestureAction.Next) != 0) Native.PostMessage(Handle, CycleMessage, new IntPtr(result.Profile * 2), activeWindow);
            if ((result.Action & GestureAction.Previous) != 0) Native.PostMessage(Handle, CycleMessage, new IntPtr(result.Profile * 2 + 1), activeWindow);
            if ((result.Action & GestureAction.HoldForward) != 0) Native.PostMessage(Handle, OutputMessage, new IntPtr(result.Profile * 2), activeWindow);
            if ((result.Action & GestureAction.HoldBackward) != 0) Native.PostMessage(Handle, OutputMessage, new IntPtr(result.Profile * 2 + 1), activeWindow);
        }
        int ownerAfter = gestures.DialOwner;
        if (ownerBefore != ownerAfter)
        {
            if (ownerBefore >= 0 && (gestures.Profiles[ownerBefore].Binding.DoubleHoldMode == "Hold a key" || gestures.Profiles[ownerBefore].Binding.DoubleHoldMode == "Dial modifier"))
                Native.PostMessage(Handle, HoldStateMessage, new IntPtr(ownerBefore * 2 + 1), activeWindow);
            if (ownerAfter >= 0 && gestures.Profiles[ownerAfter].Binding.DoubleHoldMode != "Cycle list") gestures.Profiles[ownerAfter].State.CancelTap();
            if (ownerAfter >= 0 && (gestures.Profiles[ownerAfter].Binding.DoubleHoldMode == "Hold a key" || gestures.Profiles[ownerAfter].Binding.DoubleHoldMode == "Dial modifier"))
                Native.PostMessage(Handle, HoldStateMessage, new IntPtr(ownerAfter * 2), activeWindow);
            uiDirty = true;
        }
        if (heldProfile >= 0 && !heldIsDouble && !gestures.Profiles[heldProfile].State.OrdinaryHeld)
            Native.PostMessage(Handle, HoldStateMessage, new IntPtr(heldProfile * 2 + 1), activeWindow);
        UpdateGestureTimer();
        return (result.Action & GestureAction.Consume) != 0 ? new IntPtr(1) : Native.CallNextHookEx(keyboardHook, code, message, data);
    }
    private IntPtr MouseEvent(int code, IntPtr message, IntPtr data)
    {
        if (code >= 0 && message.ToInt32() != 0x200)
        {
            var mouse = (Native.MSLLHOOKSTRUCT)Marshal.PtrToStructure(data, typeof(Native.MSLLHOOKSTRUCT));
            if (mouse.dwExtraInfo.ToUInt64() == ModifierGestures.OwnInputMarker)
                return Native.CallNextHookEx(mouseHook, code, message, data);
            int msg = message.ToInt32();
            if (msg == 0x201 || msg == 0x202) keys.Set(1, msg == 0x201);
            if (msg == 0x204 || msg == 0x205) keys.Set(2, msg == 0x204);
            if (msg == 0x207 || msg == 0x208) keys.Set(4, msg == 0x207);
            if (msg == 0x20B || msg == 0x20C) keys.Set((unchecked((uint)Marshal.ReadInt32(data, 8)) >> 16) == 1 ? 5 : 6, msg == 0x20B);
            gestures.CancelTap();
            UpdateGestureTimer();
        }
        return Native.CallNextHookEx(mouseHook, code, message, data);
    }
    private void ResetPositions() { if (cycles != null) foreach (ToolCycle c in cycles) c.Position = -1; }
    // Only reached from an input callback whose foreground/scope was checked,
    // or the isolated diagnostic fixture. Never waits for the UI message queue.
    private bool DispatchScroll(GestureResult result)
    {
        if (result.Profile < 0) return false;
        bool second = (result.Action & (GestureAction.Next | GestureAction.Previous)) != 0;
        if (!second && (result.Action & (GestureAction.HoldForward | GestureAction.HoldBackward)) == 0) return false;
        RuntimeProfile p = gestures.Profiles[result.Profile];
        if ((second ? p.Binding.DoubleHoldMode : p.Binding.HoldMode) != "Dial scrolling") return false;
        int direction = (result.Action & (GestureAction.Next | GestureAction.HoldForward)) != 0 ? 1 : -1;
        Send(scrollSession.Packet(gestures.Profiles, result.Profile, second, activeWindow, direction));
        return true;
    }
    private void UpdateGestureTimer()
    {
        bool needed = !testMode && activeWindow != IntPtr.Zero && !paused && (uiDirty || gestures.NeedsTimer(heldProfile));
        if (needed) { if (!gestureClock.Enabled) gestureClock.Start(); }
        else if (gestureClock.Enabled) gestureClock.Stop();
    }
    private bool ValidTarget(IntPtr target)
    { return !paused && !testMode && config.Enabled && target != IntPtr.Zero && target == activeWindow && target == Native.GetForegroundWindow(); }
    protected override void WndProc(ref Message m)
    {
        if (m.Msg == HoldStateMessage)
        {
            int encoded = m.WParam.ToInt32(), profile = encoded / 2;
            if (encoded % 2 != 0) { if (heldProfile == profile) EndCustomHold(); }
            else if (ValidTarget(m.LParam) && gestures.DialOwner == profile) BeginCustomHold(profile);
            return;
        }
        if (m.Msg == ReleaseMessage) { ReleaseModifier((ushort)m.WParam.ToInt32()); return; }
        if (m.Msg == TrackMessage)
        { int encoded = m.WParam.ToInt32(), p = encoded / 64, i = encoded % 64;
          if (ValidTarget(m.LParam) && p >= 0 && p < cycles.Length && i >= 0 && i < cycles[p].Tools.Count) { cycles[p].Position = i; uiDirty = true; UpdateGestureTimer(); } return; }
        if (m.Msg == CycleMessage) { int encoded = m.WParam.ToInt32(); if (ValidTarget(m.LParam)) Step(encoded / 2, encoded % 2 == 0 ? 1 : -1); return; }
        if (m.Msg == OutputMessage)
        {
            int encoded = m.WParam.ToInt32(), profile = encoded / 2;
            if (ValidTarget(m.LParam) && profile >= 0 && profile < gestures.Profiles.Length)
            {
                if (gestures.Profiles[profile].Binding.HoldMode == "Dial modifier")
                    SendOutput(profile, encoded % 2 == 0 ? gestures.Profiles[profile].Forward : gestures.Profiles[profile].Backward, gestures.DialOwner < 0, false,
                        encoded % 2 == 0 ? gestures.Profiles[profile].ForwardInputs : gestures.Profiles[profile].BackwardInputs);
                else Step(profile, encoded % 2 == 0 ? 1 : -1, false);
            }
            return;
        }
        base.WndProc(ref m);
    }
    private void ReleaseModifier(ushort key)
    {
        bool mask = ModifierGestures.IsAlt(key) && (Native.GetAsyncKeyState(0x11) & 0x8000) == 0;
        var input = new List<Native.INPUT>();
        if (mask) input.Add(InputBuilder.Key(0xA2, false)); input.Add(InputBuilder.Key(key, true)); if (mask) input.Add(InputBuilder.Key(0xA2, true));
        Emit(input.ToArray());
    }
    private void BeginCustomHold(int profile, bool doubleHold = true)
    {
        EndCustomHold(); heldProfile = profile; heldIsDouble = doubleHold;
        heldOutput = doubleHold ? (gestures.Profiles[profile].Binding.DoubleHoldMode == "Dial modifier" ? gestures.Profiles[profile].NativeModifier : gestures.Profiles[profile].HoldOutput) : gestures.Profiles[profile].OrdinaryOutput;
        if (!Send(InputBuilder.Hold(heldOutput, false))) EndCustomHold();
    }
    private void EndCustomHold()
    {
        if (heldOutput == null) return;
        KeyChord chord = heldOutput; int family = gestures.Profiles[heldProfile].State.Family;
        heldOutput = null; heldProfile = -1;
        var input = new List<Native.INPUT>();
        bool mask = chord.Key == 0xA4 || chord.Key == 0x5B || (chord.Modifiers & (KeyChord.Alt | KeyChord.Win)) != 0;
        mask = mask && !(family != 0x11 && (keys.IsDown(0xA2) || keys.IsDown(0xA3)));
        if (mask) input.Add(InputBuilder.Key(0xA2, false));
        foreach (Native.INPUT item in InputBuilder.Hold(chord, true))
            if (!keys.IsDown(item.data.ki.wVk) || KeyChord.InFamily(item.data.ki.wVk, family)) input.Add(item);
        if (mask) input.Add(InputBuilder.Key(0xA2, true));
        if (input.Count > 0) Emit(input.ToArray());
    }
    private void SendOutput(int profile, KeyChord chord, bool restore, bool tap, Native.INPUT[] prepared = null)
    {
        if (chord.IsNone) return;
        if (!ValidTarget(activeWindow)) return;
        ushort[] held = InputBuilder.HeldModifiers();
        if (tap && held.Length != 0) return;
        Native.INPUT[] input = held.Length == 0 ? (prepared ?? InputBuilder.Build(chord)) : InputBuilder.WithHeld(chord, held, restore);
        if (!Send(input)) return;
        int tool = cycles[profile].Index(chord.Key, chord.Modifiers);
        if (tool >= 0) cycles[profile].Position = tool; else if (tap) cycles[profile].Position = -1;
        uiDirty = true; UpdateGestureTimer();
    }
    private void Step(int profile, int direction, bool doubleHold = true)
    {
        if (!ValidTarget(activeWindow) || profile < 0 || profile >= cycles.Length || !config.Modifiers[profile].Enabled) return;
        ModifierBinding binding = config.Modifiers[profile];
        string mode = doubleHold ? binding.DoubleHoldMode : binding.HoldMode;
        if (mode == "Hold a key" || mode == "No action") return;
        int otherModifiers = keys.ModifierFlags;
        if (profile < gestures.Profiles.Length) otherModifiers &= ~KeyChord.FamilyFlag(gestures.Profiles[profile].State.Family);
        if (otherModifiers != 0) return;
        if (mode == "Dial scrolling")
        { scrollSession.Sync(gestures.Profiles); Send(scrollSession.Packet(gestures.Profiles, profile, doubleHold, activeWindow, direction)); return; }
        if (mode == "Dial modifier")
        { RuntimeProfile p = gestures.Profiles[profile]; SendOutput(profile, direction > 0 ? p.Forward : p.Backward, true, false, direction > 0 ? p.ForwardInputs : p.BackwardInputs); return; }
        ToolCycle cycle = cycles[profile];
        int next = cycle.Next(direction);
        if (Send(cycle.Inputs[next])) { cycle.Position = next; uiDirty = true; UpdateGestureTimer(); }
    }
    private bool Send(Native.INPUT[] input)
    {
        uint count = Emit(input);
        if (count == input.Length) return true;
        // Release any partially delivered synthetic keys. Never claim selection.
        var release = new List<Native.INPUT>();
        foreach (Native.INPUT item in input) if (item.type == 1 && (item.data.ki.dwFlags & 2) == 0) release.Add(InputBuilder.Key(item.data.ki.wVk, true));
        if (release.Count > 0) Emit(release.ToArray());
        scrollSession.Reset(); ResetPositions(); uiDirty = true; status.Text = "Windows blocked input. Keep both apps at normal privileges."; return false;
    }
    internal static int NextIndex(int current, int direction, int count)
    { return current < 0 ? (direction > 0 ? 0 : count - 1) : (current + direction + count) % count; }
    private uint Emit(Native.INPUT[] input)
    {
        if (testMode) { diagnosticInputs.AddRange(input); return (uint)input.Length; }
        return Native.SendInput((uint)input.Length, input, Native.InputSize);
    }
    internal void VerifyReleasedOutputs()
    {
        var down = new HashSet<ushort>();
        foreach (Native.INPUT input in diagnosticInputs)
            if (input.type == 1) { if ((input.data.ki.dwFlags & 2) != 0) down.Remove(input.data.ki.wVk); else down.Add(input.data.ki.wVk); }
        if (heldOutput != null || down.Count != 0) throw new Exception("A custom output was left held.");
    }
    internal void VerifyConfigUi(string report)
    {
        foreach (Control c in Controls)
            if (c is Button && (c.Text == "Match tracker" || c.Text == "Hide to tray" || c.Text == "Exit"))
                throw new Exception("Removed button still present: " + c.Text);
        using (var bitmap = new Bitmap(Width, Height)) { DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size)); bitmap.Save(report + ".main.png"); }
        using (var dialog = new ConfigForm(config)) { dialog.VerifyAndRender(report); }
        VerifyDirectScroll();
        VerifyPlainLanguage(this);
        foreach (bool second in new bool[] { false, true })
        foreach (string output in new string[] { "Space", "Ctrl", "Alt", "Shift", "Ctrl+Shift+F12" })
        {
            gestures.Profiles[0].HoldOutput = KeyChord.ParseHold(output);
            gestures.Profiles[0].OrdinaryOutput = KeyChord.ParseHold(output);
            BeginCustomHold(0, second); EndCustomHold(); VerifyReleasedOutputs();
            BeginCustomHold(0, second); DisableHooks(); VerifyReleasedOutputs();
            BeginCustomHold(0, second); RefreshScope(); VerifyReleasedOutputs();
            BeginCustomHold(0, second); ApplyConfig(config); VerifyReleasedOutputs();
        }
        // The smoke runner closes the form next; Dispose must release this too.
        config.Modifiers[0].DoubleHoldMode = "Dial modifier";
        BeginCustomHold(0); EndCustomHold(); VerifyReleasedOutputs();
        if (gestureClock.Enabled) throw new Exception("Idle diagnostic form kept its fast timer running.");
        BeginCustomHold(0);
    }
    private static void VerifyPlainLanguage(Control parent)
    {
        foreach (Control c in parent.Controls)
        { if (c.Text.Contains("-_") || c.Text.Contains("Original modifier")) throw new Exception("Obsolete interface notation/name."); VerifyPlainLanguage(c); }
    }
    private void VerifyDirectScroll()
    {
        AppSettings saved = config.Clone();
        foreach (bool second in new bool[] { false, true })
        for (int owner = 0; owner < 3; owner++)
        {
            AppSettings settings = saved.Clone(); settings.Modifiers[owner].HoldMode = settings.Modifiers[owner].DoubleHoldMode = "Dial scrolling";
            ApplyConfig(settings); keys.Clear(); diagnosticInputs.Clear();
            int modifier = owner == 0 ? 0xA4 : owner == 1 ? 0xA2 : 0xA0; uint now = 100;
            if (second) { ScrollSession.Event(gestures, keys, modifier, true, now++); ScrollSession.Event(gestures, keys, modifier, false, now++); }
            ScrollSession.Event(gestures, keys, modifier, true, now++);
            for (int i = 0; i < 1000; i++)
            {
                int key = i % 2 == 0 ? 0xDD : 0xDB;
                GestureResult result = ScrollSession.Event(gestures, keys, key, true, now++); scrollSession.Sync(gestures.Profiles);
                int before = diagnosticInputs.Count;
                if (!DispatchScroll(result) || diagnosticInputs.Count <= before) throw new Exception("Scrolling waited for queued UI work.");
                if (i > 0 && diagnosticInputs.Count != before + 1) throw new Exception("Steady scrolling emitted extra keyboard input.");
                Native.INPUT last = diagnosticInputs[diagnosticInputs.Count - 1];
                if (last.type != 0 || last.data.mi.mouseData != (i % 2 == 0 ? 120u : unchecked((uint)-120))) throw new Exception("Direct scrolling lost/reordered input.");
                ScrollSession.Event(gestures, keys, key, false, now++);
            }
            for (int i = 0; i < 1000; i++)
            {
                GestureResult result = ScrollSession.Event(gestures, keys, 0xDD, true, now++); scrollSession.Sync(gestures.Profiles);
                int before = diagnosticInputs.Count;
                if (!DispatchScroll(result) || diagnosticInputs.Count != before + 1) throw new Exception("Overlapping controller notches were delayed or lost.");
            }
            ScrollSession.Event(gestures, keys, 0xDD, false, now++);
            ScrollSession.Event(gestures, keys, modifier, false, now++); scrollSession.Sync(gestures.Profiles); VerifyReleasedOutputs();
        }
        diagnosticInputs.Clear(); keys.Clear(); ApplyConfig(saved);
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            scopeClock.Stop(); scopeClock.Dispose(); gestureClock.Stop(); gestureClock.Dispose(); DisableHooks();
            if (foregroundHook != IntPtr.Zero) { Native.UnhookWinEvent(foregroundHook); foregroundHook = IntPtr.Zero; }
            tray.Visible = false; tray.Dispose(); trayMenu.Dispose();
        }
        base.Dispose(disposing);
    }
    internal static void SelfTest()
    {
        AppSettings.SelfTest(); ModifierGestures.SelfTest(); KeySnapshot.SelfTest(); GestureBank.SelfTest(); InputBuilder.SelfTest(); ToolCycle.SelfTest(); ScrollSession.SelfTest();
        foreach (int count in new int[] { 1, 2, 20, 64 })
        {
            if (NextIndex(-1, 1, count) != 0 || NextIndex(-1, -1, count) != count - 1) throw new Exception("Cycle anchors.");
            for (int i = 0; i < count; i++)
                if (NextIndex(NextIndex(i, 1, count), -1, count) != i) throw new Exception("Cycle round-trip.");
        }
    }
}

