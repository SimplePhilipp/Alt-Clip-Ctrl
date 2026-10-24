using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

internal sealed class ConfigForm : Form
{
    internal AppSettings Result;
    private readonly CheckBox enabled = new CheckBox(), detection = new CheckBox();
    private readonly TabControl tabs = new TabControl();
    private readonly List<ProfileEditor> profiles = new List<ProfileEditor>();
    private readonly DataGridView tools = new DataGridView();
    private readonly string notation =
        "THE TAP / HOLD NOTATION\r\n\r\n" +
        "- means tap: press a key and release it quickly.\r\n" +
        "_ means hold: keep a key pressed.\r\n" +
        "-_ means tap, release, then press and hold the same key again.\r\n" +
        "+ joins keys pressed together.\r\n\r\n" +
        "EXAMPLES WITH THE DEFAULT BINDINGS\r\n\r\n" +
        "-Alt        Tap Alt -> sends B after 100 ms.\r\n" +
        "_Alt        Hold Alt -> normal Alt.\r\n" +
        "_Alt + ]    Hold Alt and press ] -> sends F.\r\n" +
        "_Alt + [    Hold Alt and press [ -> sends S.\r\n" +
        "-_Alt       Tap Alt, release, then hold Alt again -> dial cycling.\r\n" +
        "-_Alt + ]   In that held-second-press mode, ] selects the next tool.\r\n\r\n" +
        "Replace Alt with Ctrl or Shift for their profiles. Each profile can\r\n" +
        "be enabled or disabled and can have different inputs and outputs.\r\n" +
        "An ordinary hold always stays the original modifier.\r\n\r\n" +
        "Start the second press within the configured tap-wait window.\r\n" +
        "B waits for that same window so dial entry does not also send B.\r\n" +
        "Release the second held press to leave dial mode.\r\n\r\n" +
        "Shortcut text examples: B, F12, Space, Ctrl+Shift+F1, Alt+Left.\r\n" +
        "Use Plus or Minus for those keys. Outputs can be key combinations;\r\n" +
        "rotation inputs must be single keyboard keys. CSP assignments must\r\n" +
        "match the Tools tab; this app does not edit CSP's settings.";

    internal ConfigForm(AppSettings settings)
    {
        Text = "Alt Clip Ctrl - Config"; Font = new Font("Segoe UI", 10);
        ClientSize = new Size(760, 655); FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; MinimizeBox = false; StartPosition = FormStartPosition.CenterParent;
        enabled.Text = "Enable Alt Clip Ctrl"; enabled.SetBounds(18, 14, 270, 26);
        detection.Text = "Auto-detect Clip Studio Paint"; detection.SetBounds(320, 14, 400, 26);
        var scope = new Label { Text = "Detection on: CSP only. Detection off: other apps too. Config is always excluded.",
            Location = new Point(18, 44), Size = new Size(724, 24) };
        tabs.SetBounds(14, 78, 732, 510);
        var save = new Button { Text = "Save", Location = new Point(596, 606), Size = new Size(150, 35) };
        var cancel = new Button { Text = "Cancel", Location = new Point(432, 606), Size = new Size(150, 35), DialogResult = DialogResult.Cancel };
        var defaults = new Button { Text = "Restore defaults", Location = new Point(14, 606), Size = new Size(180, 35) };
        save.Click += delegate {
            try { Result = ReadSettings(); Result.Validate(); DialogResult = DialogResult.OK; Close(); }
            catch (Exception ex) { MessageBox.Show(this, ex.Message, "Check config", MessageBoxButtons.OK, MessageBoxIcon.Information); }
        };
        defaults.Click += delegate { LoadSettings(AppSettings.Defaults()); };
        Controls.AddRange(new Control[] { enabled, detection, scope, tabs, save, cancel, defaults });
        CancelButton = cancel;
        LoadSettings(settings.Clone());
    }
    private void LoadSettings(AppSettings settings)
    {
        if (tools.Parent != null) tools.Parent.Controls.Remove(tools);
        while (tabs.TabPages.Count > 0) { TabPage old = tabs.TabPages[0]; tabs.TabPages.RemoveAt(0); old.Dispose(); }
        profiles.Clear();
        enabled.Checked = settings.Enabled; detection.Checked = settings.DetectClipStudio;
        foreach (ModifierBinding p in settings.Modifiers)
        {
            var tab = new TabPage(p.Modifier);
            var editor = new ProfileEditor(p); editor.Dock = DockStyle.Fill;
            tab.Controls.Add(editor); tabs.TabPages.Add(tab); profiles.Add(editor);
        }
        var toolTab = new TabPage("Tools");
        var help = new Label { Text = "Tool order and CSP shortcuts. Edit cells, use Record, or add a row at the bottom.",
            Location = new Point(12, 12), Size = new Size(680, 24) };
        tools.SetBounds(12, 44, 696, 372); tools.Columns.Clear(); tools.Rows.Clear();
        tools.AllowUserToAddRows = true; tools.AllowUserToDeleteRows = true; tools.AutoGenerateColumns = false;
        tools.RowHeadersWidth = 40; tools.SelectionMode = DataGridViewSelectionMode.FullRowSelect; tools.MultiSelect = false;
        tools.BackgroundColor = Color.White; tools.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill;
        tools.Columns.Add(new DataGridViewTextBoxColumn { Name = "Tool", HeaderText = "Tool name", FillWeight = 45 });
        tools.Columns.Add(new DataGridViewTextBoxColumn { Name = "Shortcut", HeaderText = "Shortcut", FillWeight = 35 });
        tools.Columns.Add(new DataGridViewButtonColumn { Name = "Record", HeaderText = "", Text = "Record", UseColumnTextForButtonValue = true, FillWeight = 20 });
        foreach (ToolBinding tool in settings.Tools) tools.Rows.Add(tool.Name, tool.Shortcut);
        tools.CellContentClick -= RecordTool; tools.CellContentClick += RecordTool;
        var up = new Button { Text = "Move up", Location = new Point(12, 431), Size = new Size(130, 33) };
        var down = new Button { Text = "Move down", Location = new Point(152, 431), Size = new Size(130, 33) };
        var remove = new Button { Text = "Remove tool", Location = new Point(292, 431), Size = new Size(145, 33) };
        up.Click += delegate { MoveTool(-1); }; down.Click += delegate { MoveTool(1); };
        remove.Click += delegate { if (tools.CurrentRow != null && !tools.CurrentRow.IsNewRow) tools.Rows.Remove(tools.CurrentRow); };
        toolTab.Controls.AddRange(new Control[] { help, tools, up, down, remove }); tabs.TabPages.Add(toolTab);
        var notationTab = new TabPage("Notation");
        var text = new TextBox { Multiline = true, ReadOnly = true, BorderStyle = BorderStyle.None, BackColor = Color.White,
            ScrollBars = ScrollBars.Vertical, Font = new Font("Consolas", 10), Text = notation, Dock = DockStyle.Fill };
        notationTab.Padding = new Padding(14); notationTab.Controls.Add(text); tabs.TabPages.Add(notationTab);
    }
    private void RecordTool(object sender, DataGridViewCellEventArgs e)
    {
        if (e.RowIndex < 0 || e.ColumnIndex != 2) return;
        using (var dialog = new CaptureKeyForm(false))
            if (dialog.ShowDialog(this) == DialogResult.OK)
            {
                int row = e.RowIndex;
                if (tools.Rows[row].IsNewRow) row = tools.Rows.Add("New tool", dialog.Shortcut);
                else tools.Rows[row].Cells[1].Value = dialog.Shortcut;
            }
    }
    private void MoveTool(int direction)
    {
        tools.EndEdit(); if (tools.CurrentRow == null || tools.CurrentRow.IsNewRow) return;
        int from = tools.CurrentRow.Index, to = from + direction;
        if (to < 0 || to >= tools.Rows.Count || tools.Rows[to].IsNewRow) return;
        for (int i = 0; i < 2; i++) { object value = tools.Rows[from].Cells[i].Value; tools.Rows[from].Cells[i].Value = tools.Rows[to].Cells[i].Value; tools.Rows[to].Cells[i].Value = value; }
        tools.CurrentCell = tools.Rows[to].Cells[0];
    }
    internal AppSettings ReadSettings()
    {
        tools.EndEdit();
        var s = new AppSettings { Enabled = enabled.Checked, DetectClipStudio = detection.Checked,
            Modifiers = new List<ModifierBinding>(), Tools = new List<ToolBinding>() };
        foreach (ProfileEditor editor in profiles) s.Modifiers.Add(editor.Read());
        foreach (DataGridViewRow row in tools.Rows)
        {
            if (row.IsNewRow) continue;
            string name = Convert.ToString(row.Cells[0].Value).Trim(), key = Convert.ToString(row.Cells[1].Value).Trim();
            if (name.Length == 0 && key.Length == 0) continue;
            s.Tools.Add(new ToolBinding { Name = name, Shortcut = key });
        }
        return s;
    }
    internal void VerifyAndRender(string report)
    {
        IntPtr handle = Handle; CreateControl();
        AppSettings fromUi = ReadSettings(); fromUi.Validate();
        if (tabs.TabPages.Count != 5 || fromUi.Modifiers.Count != 3) throw new Exception("Config tabs missing.");
        for (int i = 0; i < tabs.TabPages.Count; i++)
        {
            tabs.SelectedIndex = i; CreateHandles(this); PerformLayout();
            using (var bitmap = new Bitmap(Width, Height))
            { DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size)); bitmap.Save(report + ".config-" + i + ".png"); }
        }
    }
    private static void CreateHandles(Control control)
    {
        IntPtr handle = control.Handle;
        foreach (Control child in control.Controls) CreateHandles(child);
    }
}

internal sealed class ProfileEditor : UserControl
{
    private readonly string modifier;
    private readonly CheckBox enabled = new CheckBox();
    private readonly Panel fields = new Panel();
    private readonly TextBox next = new TextBox(), previous = new TextBox(), tap = new TextBox(), forward = new TextBox(), backward = new TextBox();
    private readonly NumericUpDown wait = new NumericUpDown(), shortMax = new NumericUpDown();
    internal ProfileEditor(ModifierBinding p)
    {
        modifier = p.Modifier;
        enabled.Text = "Enable " + modifier + " gestures"; enabled.SetBounds(18, 16, 500, 28); enabled.Checked = p.Enabled;
        fields.SetBounds(0, 52, 716, 420); fields.Enabled = p.Enabled;
        enabled.CheckedChanged += delegate { fields.Enabled = enabled.Checked; };
        AddRow("Forward / next input", next, p.NextInput, 0, true);
        AddRow("Backward / previous input", previous, p.PreviousInput, 48, true);
        AddRow("-" + modifier + " output", tap, p.TapOutput, 96, false);
        AddRow("_" + modifier + " + forward input output", forward, p.HoldNextOutput, 144, false);
        AddRow("_" + modifier + " + backward input output", backward, p.HoldPreviousOutput, 192, false);
        AddNumber("Tap wait / second-press window (ms)", wait, p.TapWaitMs, 246);
        AddNumber("Maximum short press (ms)", shortMax, p.ShortPressMs, 294);
        fields.Controls.Add(new Label { Text = "_" + modifier + " alone stays normal " + modifier + ".\r\n-_" + modifier + " enables tool cycling while the second press is held.\r\nOutput example: Ctrl+Shift+F1. Rotation inputs must be single keys.",
            Location = new Point(18, 350), Size = new Size(680, 70) });
        Controls.Add(enabled); Controls.Add(fields);
    }
    private void AddRow(string title, TextBox box, string value, int y, bool single)
    {
        fields.Controls.Add(new Label { Text = title, Location = new Point(18, y + 5), Size = new Size(310, 30) });
        box.Text = value; box.SetBounds(335, y, 225, 30); fields.Controls.Add(box);
        var record = new Button { Text = "Record", Location = new Point(574, y - 1), Size = new Size(122, 32) };
        record.Click += delegate { using (var dialog = new CaptureKeyForm(single)) if (dialog.ShowDialog(this) == DialogResult.OK) box.Text = dialog.Shortcut; };
        fields.Controls.Add(record);
    }
    private void AddNumber(string title, NumericUpDown box, int value, int y)
    {
        fields.Controls.Add(new Label { Text = title, Location = new Point(18, y + 5), Size = new Size(310, 30) });
        box.Minimum = 20; box.Maximum = 2000; box.Value = Math.Max(20, Math.Min(2000, value)); box.Increment = 10;
        box.SetBounds(335, y, 225, 30); fields.Controls.Add(box);
    }
    internal ModifierBinding Read()
    {
        return new ModifierBinding { Modifier = modifier, Enabled = enabled.Checked, NextInput = KeyChord.Parse(next.Text).ToString(),
            PreviousInput = KeyChord.Parse(previous.Text).ToString(), TapOutput = KeyChord.Parse(tap.Text).ToString(),
            HoldNextOutput = KeyChord.Parse(forward.Text).ToString(), HoldPreviousOutput = KeyChord.Parse(backward.Text).ToString(),
            TapWaitMs = (int)wait.Value, ShortPressMs = (int)shortMax.Value };
    }
}

internal sealed class CaptureKeyForm : Form
{
    internal string Shortcut;
    private readonly bool single;
    private readonly Label prompt = new Label();
    internal CaptureKeyForm(bool oneKey)
    {
        single = oneKey; Text = "Alt Clip Ctrl - Record key"; Font = new Font("Segoe UI", 10);
        ClientSize = new Size(450, 150); FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = MinimizeBox = false;
        StartPosition = FormStartPosition.CenterParent; KeyPreview = true;
        prompt.Text = oneKey ? "Press one keyboard key, without modifiers." : "Press a key or combination, such as Ctrl+Shift+F1.";
        prompt.SetBounds(18, 20, 414, 66); Controls.Add(prompt);
        var cancel = new Button { Text = "Cancel", Location = new Point(300, 100), Size = new Size(130, 34), DialogResult = DialogResult.Cancel };
        Controls.Add(cancel);
        KeyDown += CaptureKey;
    }
    private void CaptureKey(object sender, KeyEventArgs e)
    {
        e.Handled = e.SuppressKeyPress = true;
        int key = (int)e.KeyCode;
        if (key == 0x10 || key == 0x11 || key == 0x12 || key == 0x5B || key == 0x5C || (key >= 0xA0 && key <= 0xA5)) return;
        int flags = (e.Control ? KeyChord.Control : 0) | (e.Alt ? KeyChord.Alt : 0) | (e.Shift ? KeyChord.Shift : 0);
        if (single && flags != 0) { prompt.Text = "Release modifiers, then press one key. You can also type a key name in Config."; return; }
        Shortcut = new KeyChord { Key = (ushort)key, Modifiers = flags }.ToString();
        DialogResult = DialogResult.OK; Close();
    }
}

