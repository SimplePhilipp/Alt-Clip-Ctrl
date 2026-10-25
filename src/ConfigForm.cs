using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

internal sealed class ConfigForm : Form
{
    internal AppSettings Result;
    private readonly CheckBox enabled = new CheckBox(), detection = new CheckBox();
    private readonly Label dirty = new Label();
    private readonly TabControl tabs = new TabControl();
    private readonly List<ProfileEditor> profiles = new List<ProfileEditor>();
    private bool loading;
    internal ConfigForm(AppSettings settings)
    {
        Text = "Alt Clip Ctrl - Config"; Font = new Font("Segoe UI", 10);
        ClientSize = new Size(920, 680); FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = MinimizeBox = false; StartPosition = FormStartPosition.CenterParent;
        enabled.Text = "Enable Alt Clip Ctrl"; enabled.SetBounds(18, 14, 255, 28);
        detection.Text = "Only in Clip Studio Paint"; detection.SetBounds(300, 14, 300, 28);
        var help = new Button { Text = "Gesture help", Location = new Point(758, 12), Size = new Size(144, 30) };
        help.Click += delegate { MessageBox.Show(this,
            "Tap: press and release.\r\nHold: press and keep holding.\r\nTap then hold: tap, release, then press and keep holding again.\r\n\r\nChoose each gesture's action independently. Hold and Tap then hold offer the same actions.\r\n\r\nHeld-key actions start after Maximum short press for Hold, or on the second press for Tap then hold. Dial steps act immediately.\r\n\r\nNo action sends nothing. Dial modifier keeps the selected modifier held between dial steps. Scrolling acts at the mouse pointer. Cycle shortcuts must match CSP.",
            "Gesture help", MessageBoxButtons.OK, MessageBoxIcon.Information); };
        var scope = new Label { Text = "Detection off: bindings work in other apps too. This Config window is always excluded.",
            Location = new Point(18, 48), Size = new Size(884, 26) };
        tabs.SetBounds(14, 80, 892, 526);
        var save = new Button { Text = "Save", Location = new Point(762, 628), Size = new Size(144, 36) };
        var cancel = new Button { Text = "Cancel", Location = new Point(606, 628), Size = new Size(144, 36), DialogResult = DialogResult.Cancel };
        var defaults = new Button { Text = "Restore defaults", Location = new Point(14, 628), Size = new Size(160, 36) };
        dirty.SetBounds(190, 636, 390, 26);
        save.Click += delegate {
            try { Result = ReadSettings(); Result.Validate(); DialogResult = DialogResult.OK; Close(); }
            catch (Exception ex) { MessageBox.Show(this, ex.Message, "Check config", MessageBoxButtons.OK, MessageBoxIcon.Information); }
        };
        defaults.Click += delegate { LoadSettings(AppSettings.Defaults()); MarkDirty(); };
        enabled.CheckedChanged += delegate { MarkDirty(); }; detection.CheckedChanged += delegate { MarkDirty(); };
        Controls.AddRange(new Control[] { enabled, detection, help, scope, tabs, save, cancel, defaults, dirty }); CancelButton = cancel;
        LoadSettings(settings.Clone());
    }
    private void MarkDirty() { if (!loading) { dirty.Text = "Unsaved changes"; dirty.ForeColor = Color.FromArgb(150, 80, 0); } }
    private void LoadSettings(AppSettings settings)
    {
        loading = true; profiles.Clear();
        while (tabs.TabPages.Count > 0) { TabPage old = tabs.TabPages[0]; tabs.TabPages.RemoveAt(0); old.Dispose(); }
        enabled.Checked = settings.Enabled; detection.Checked = settings.DetectClipStudio;
        var bindings = new List<ModifierBinding>(settings.Modifiers);
        foreach (ModifierBinding binding in bindings)
        {
            var editor = new ProfileEditor(binding); editor.Dock = DockStyle.Fill; editor.Changed += delegate { MarkDirty(); };
            var tab = new TabPage(binding.Modifier); tab.Controls.Add(editor); tabs.TabPages.Add(tab); profiles.Add(editor);
        }
        dirty.Text = "No unsaved changes"; dirty.ForeColor = Color.DimGray; loading = false;
    }
    internal AppSettings ReadSettings()
    {
        var settings = new AppSettings { Enabled = enabled.Checked, DetectClipStudio = detection.Checked, Modifiers = new List<ModifierBinding>() };
        for (int i = 0; i < profiles.Count; i++) { ModifierBinding p = profiles[i].Read(); settings.Modifiers.Add(p); }
        return settings;
    }
    internal void VerifyAndRender(string report)
    {
        IntPtr handle = Handle; CreateControl();
        AppSettings before = ReadSettings().Clone(); before.Validate();
        if (tabs.TabPages.Count != 3) throw new Exception("Only Alt, Ctrl and Shift tabs should be shown.");
        for (int i = 0; i < profiles.Count; i++)
        {
            tabs.SelectedIndex = i; CreateHandles(this); PerformLayout();
            using (var bitmap = new Bitmap(Width, Height)) { DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size)); bitmap.Save(report + ".config-" + i + ".png"); }
            profiles[i].VerifyActions();
        }
        tabs.SelectedIndex = 0;
        profiles[0].PreviewAction(2, "Cycle list"); SavePreview(report + ".cycle.png");
        profiles[0].PreviewAction(1, "Hold a key"); SavePreview(report + ".hold.png");
        tabs.SelectedIndex = 0;
        profiles[0].PreviewAction(1, "Dial scrolling"); SavePreview(report + ".scroll.png");
        profiles[0].PreviewAction(2, "No action"); SavePreview(report + ".none.png");
        if (dirty.Text != "Unsaved changes") throw new Exception("Unsaved indicator did not update.");
        AppSettings edited = ReadSettings(); edited.Validate();
        LoadSettings(edited); AppSettings reloaded = ReadSettings(); reloaded.Validate();
        if (reloaded.Modifiers[1].Tools.Count != edited.Modifiers[1].Tools.Count)
            throw new Exception("Redesigned config round-trip.");
        LoadSettings(before);
    }
    internal static void CreateHandles(Control c) { IntPtr h = c.Handle; foreach (Control child in c.Controls) CreateHandles(child); }
    private void SavePreview(string path)
    { CreateHandles(this); PerformLayout(); using (var b = new Bitmap(Width, Height)) { DrawToBitmap(b, new Rectangle(Point.Empty, b.Size)); b.Save(path); } }
}

internal sealed class ProfileEditor : UserControl
{
    internal event EventHandler Changed;
    private readonly ModifierBinding model;
    private readonly CheckBox enabled = new CheckBox(), advanced = new CheckBox(), reverse = new CheckBox();
    private readonly TextBox next = new TextBox(), previous = new TextBox();
    private readonly ComboBox output = OutputBox(), forward = OutputBox(), backward = OutputBox();
    private readonly NumericUpDown wait = Number(20, 2000), shortMax = Number(20, 2000), amount = Number(1, 20);
    private readonly List<Button> gestures = new List<Button>();
    private readonly Panel detail = new Panel(), advancedFields = new Panel();
    private readonly FlowLayoutPanel choices = new FlowLayoutPanel();
    private readonly List<RadioButton> modes = new List<RadioButton>();
    private readonly Label detailTitle = new Label(), preview = new Label(), explanation = new Label();
    private readonly Panel outputRow = new Panel(), forwardRow = new Panel(), backwardRow = new Panel(), scrollFields = new Panel();
    private readonly CycleEditor cycle;
    private readonly Panel cyclePanel = new Panel();
    private int selected;
    private bool updating;
    private bool cycleShown;
    private readonly string[] titles;
    private static readonly string[] HoldActions = { "No action", "Dial modifier", "Cycle list", "Dial scrolling", "Hold a key" };
    internal ProfileEditor(ModifierBinding binding)
    {
        model = binding;
        titles = new string[] { "Tap", "Hold", "Tap then hold" };
        BackColor = Color.WhiteSmoke;
        enabled.Text = "Enable " + model.Modifier + " gestures"; enabled.SetBounds(14, 10, 450, 28); enabled.Checked = model.Enabled;
        var hint = new Label { Text = "Tap, Hold and Tap then hold have separate actions.",
            Location = new Point(450, 14), Size = new Size(420, 24), ForeColor = Color.DimGray };
        for (int i = 0; i < titles.Length; i++)
        {
            int index = i;
            var button = new Button { Location = new Point(14, 49 + i * 63), Size = new Size(270, 57), TextAlign = ContentAlignment.MiddleLeft, FlatStyle = FlatStyle.Flat };
            button.Click += delegate { SaveVisible(); selected = index; Render(); };
            gestures.Add(button); Controls.Add(button);
        }
        int inputY = 255;
        var inputs = new GroupBox { Text = "Dial input keys", Location = new Point(14, inputY), Size = new Size(270, 108) };
        InputRow(inputs, "Clockwise", next, model.NextInput, 24); InputRow(inputs, "Counterclockwise", previous, model.PreviousInput, 61);
        advanced.Text = "Advanced timing"; advanced.SetBounds(14, 376, 270, 28);
        advancedFields.SetBounds(14, 408, 270, 76); advancedFields.Visible = false;
        AddLabel(advancedFields, "Tap / second press (ms)", 0, 5, 172); wait.SetBounds(178, 0, 88, 28); wait.Value = model.TapWaitMs;
        AddLabel(advancedFields, "Maximum short press", 0, 43, 172); shortMax.SetBounds(178, 38, 88, 28); shortMax.Value = model.ShortPressMs;
        advancedFields.Controls.AddRange(new Control[] { wait, shortMax });
        advanced.CheckedChanged += delegate { advancedFields.Visible = advanced.Checked; };
        detail.SetBounds(300, 49, 570, 365); detail.BackColor = Color.White; detail.BorderStyle = BorderStyle.FixedSingle;
        detailTitle.Font = new Font(Font, FontStyle.Bold); detailTitle.SetBounds(16, 12, 536, 26);
        choices.SetBounds(12, 43, 540, 65); choices.WrapContents = true;
        MakeOutputRow(outputRow, "Output", output, false); outputRow.SetBounds(12, 116, 540, 43);
        MakeOutputRow(forwardRow, "Clockwise", forward, false); forwardRow.SetBounds(12, 116, 540, 43);
        MakeOutputRow(backwardRow, "Counterclockwise", backward, false); backwardRow.SetBounds(12, 165, 540, 43);
        scrollFields.SetBounds(12, 116, 540, 82);
        AddLabel(scrollFields, "Notches per dial step", 4, 7, 240); amount.SetBounds(270, 2, 110, 28); amount.Value = model.ScrollAmount;
        reverse.Text = "Reverse scroll direction"; reverse.SetBounds(4, 43, 440, 28); reverse.Checked = model.ReverseScroll; scrollFields.Controls.AddRange(new Control[] { amount, reverse });
        cycle = new CycleEditor(model.Tools); cycle.Dock = DockStyle.Fill; cyclePanel.SetBounds(12, 112, 540, 238); cyclePanel.Controls.Add(cycle);
        explanation.SetBounds(16, 222, 536, 115); explanation.ForeColor = Color.DimGray;
        detail.Controls.AddRange(new Control[] { detailTitle, choices, outputRow, forwardRow, backwardRow, scrollFields, explanation, cyclePanel });
        preview.SetBounds(300, 427, 570, 57); preview.BackColor = Color.FromArgb(231, 240, 249); preview.Padding = new Padding(10, 8, 8, 0);
        Controls.AddRange(new Control[] { enabled, hint, inputs, advanced, advancedFields, detail, preview });
        enabled.CheckedChanged += delegate { Notify(); RenderEnabled(); };
        foreach (Control c in new Control[] { next, previous, output, forward, backward }) c.TextChanged += delegate { if (!updating) { SaveVisible(); UpdateSummaries(); Notify(); } };
        foreach (NumericUpDown n in new NumericUpDown[] { wait, shortMax, amount }) n.ValueChanged += delegate { if (!updating) { SaveVisible(); UpdateSummaries(); Notify(); } };
        reverse.CheckedChanged += delegate { if (!updating) { SaveVisible(); Notify(); } };
        cycle.Changed += delegate { if (!updating) Notify(); };
        Render();
    }
    private static NumericUpDown Number(int min, int max) { return new NumericUpDown { Minimum = min, Maximum = max }; }
    private static ComboBox OutputBox()
    { var c = new ComboBox { DropDownStyle = ComboBoxStyle.DropDown }; c.Items.AddRange(new object[] { "No action", "Scroll up", "Scroll down", "B", "F", "S", "Space" }); return c; }
    private void Notify() { if (Changed != null) Changed(this, EventArgs.Empty); }
    private static void AddLabel(Control parent, string text, int x, int y, int width)
    { parent.Controls.Add(new Label { Text = text, Location = new Point(x, y), Size = new Size(width, 28) }); }
    private void InputRow(Control parent, string title, TextBox box, string text, int y)
    {
        AddLabel(parent, title, 10, y + 4, 130); box.SetBounds(142, y, 58, 28); box.Text = text;
        var record = new Button { Text = "Set", Location = new Point(205, y - 1), Size = new Size(54, 30) };
        record.Click += delegate { using (var d = new CaptureKeyForm(true)) if (d.ShowDialog(this) == DialogResult.OK) box.Text = d.Shortcut; };
        parent.Controls.AddRange(new Control[] { box, record });
    }
    private void MakeOutputRow(Panel row, string title, ComboBox box, bool hold)
    {
        AddLabel(row, title, 4, 8, 155); box.SetBounds(166, 3, 255, 29);
        var record = new Button { Text = "Record", Location = new Point(432, 2), Size = new Size(100, 31) };
        record.Click += delegate { using (var d = new CaptureKeyForm(false)) if (d.ShowDialog(this) == DialogResult.OK) box.Text = d.Shortcut; };
        row.Controls.AddRange(new Control[] { box, record });
    }
    private string CurrentMode()
    {
        if (selected == 0) return model.TapOutput == "No action" ? "No action" : "Key / shortcut";
        return selected == 1 ? model.HoldMode : model.DoubleHoldMode;
    }
    private void SaveVisible()
    {
        if (updating) return;
        model.Enabled = enabled.Checked; model.NextInput = next.Text; model.PreviousInput = previous.Text;
        model.TapWaitMs = (int)wait.Value; model.ShortPressMs = (int)shortMax.Value;
        model.ScrollAmount = (int)amount.Value; model.ReverseScroll = reverse.Checked;
        if (selected == 0) { if (CurrentMode() == "Key / shortcut") model.TapOutput = output.Text; }
        else if (selected == 1) model.HoldOutput = output.Text;
        else model.DoubleHoldOutput = output.Text;
        model.HoldNextOutput = forward.Text; model.HoldPreviousOutput = backward.Text;
    }
    private void Render()
    {
        updating = true;
        string current = CurrentMode();
        detailTitle.Text = titles[selected] + " action";
        output.Items.Clear();
        output.Items.AddRange(selected == 0 ? new object[] { "B", "F", "S", "Space", "Ctrl+Z" } : new object[] { "Space", "Ctrl", "Alt", "Shift", "B" });
        output.Text = selected == 0 ? model.TapOutput : selected == 1 ? model.HoldOutput : model.DoubleHoldOutput;
        forward.Text = model.HoldNextOutput; backward.Text = model.HoldPreviousOutput;
        while (choices.Controls.Count > 0) choices.Controls[0].Dispose(); modes.Clear();
        string[] options = selected == 0 ? new string[] { "No action", "Key / shortcut" } : HoldActions;
        foreach (string option in options)
        {
            string value = option;
            var radio = new RadioButton { Text = option, AutoSize = true, Checked = current == option, Margin = new Padding(4, 7, 15, 5) };
            radio.CheckedChanged += delegate {
                if (updating || !radio.Checked) return;
                SaveVisible();
                if (selected == 0) model.TapOutput = value == "Key / shortcut" ? "B" : value;
                else if (selected == 1) model.HoldMode = value; else model.DoubleHoldMode = value;
                Render(); Notify();
            };
            modes.Add(radio); choices.Controls.Add(radio);
        }
        bool native = current == "Dial modifier" || current == "Custom outputs";
        outputRow.Visible = current == "Key / shortcut" || current == "Hold a key";
        forwardRow.Visible = backwardRow.Visible = native;
        scrollFields.Visible = current == "Dial scrolling";
        cycleShown = current == "Cycle list"; cyclePanel.Visible = cycleShown; explanation.Visible = !cycleShown;
        explanation.Text = current == "No action" ? "This gesture sends nothing. Dial steps in this gesture also do nothing.\r\nTo keep a normal native modifier hold, choose Dial modifier."
            : current == "Hold a key" ? "The chosen key or chord stays pressed until you release the gesture.\r\nFor Hold, it starts after Maximum short press (Advanced).\r\nFor Tap then hold, it starts on the second press."
            : current == "Dial scrolling" ? "Scrolling acts at the mouse pointer.\r\nHover over a slider or scrollable area before turning."
            : native ? "The input keys on the left trigger these outputs.\r\nDial modifier keeps the native modifier held between steps."
            : "Choose a keyboard key or shortcut for Tap.";
        updating = false; UpdateSummaries(); RenderEnabled();
    }
    private void RenderEnabled() { detail.Enabled = true; foreach (Button b in gestures) b.Enabled = true; preview.ForeColor = enabled.Checked ? Color.Black : Color.DimGray; }
    private void UpdateSummaries()
    {
        for (int i = 0; i < gestures.Count; i++)
        {
            string summary = i == 0 ? model.TapOutput : i == 1 ? model.HoldMode : model.DoubleHoldMode;
            gestures[i].Text = titles[i] + "\r\n" + summary;
            gestures[i].BackColor = i == selected ? Color.FromArgb(219, 234, 249) : SystemColors.Control;
        }
        string mode = CurrentMode();
        string start = selected == 0 ? "Tap " + model.Modifier + ": " : selected == 1 ? "Hold " + model.Modifier + ": " : "Tap " + model.Modifier + ", release, then hold it: ";
        preview.Text = start + (mode == "No action" ? "do nothing." : mode == "Cycle list" ? "turn to cycle this list." : mode == "Dial scrolling" ? "turn to scroll at the pointer." : mode == "Hold a key" ? "hold " + (selected == 1 ? model.HoldOutput : model.DoubleHoldOutput) + " until release." : mode == "Dial modifier" ? "keep normal " + model.Modifier + "; turn for the configured outputs." : mode == "Custom outputs" ? "send the configured clockwise/counterclockwise outputs." : "send " + model.TapOutput + ".");
    }
    internal ModifierBinding Read() { SaveVisible(); model.Tools = cycle.Read(); return model; }
    internal void PreviewAction(int gesture, string mode)
    { SaveVisible(); selected = gesture; Render(); foreach (RadioButton r in modes.ToArray()) if (r.Text == mode) { r.Checked = true; break; } }
    internal void VerifyActions()
    {
        int saved = selected;
        {
            PreviewAction(0, "Key / shortcut"); output.Text = "F12";
            selected = 1; Render(); selected = 0; Render();
            if (output.Text != "F12") throw new Exception("Switching gestures lost an unsaved output.");
        }
        cycle.VerifyEditing(model.Modifier);
        for (int i = 0; i < titles.Length; i++)
        {
            SaveVisible(); selected = i; Render();
            int count = modes.Count;
            if (i == 0)
            {
                if (count != 2 || modes[0].Text != "No action" || modes[1].Text != "Key / shortcut") throw new Exception("Tap has unexpected action choices.");
                foreach (object item in output.Items) if (Convert.ToString(item).StartsWith("Scroll")) throw new Exception("Tap still offers scrolling.");
            }
            else
            { if (count != HoldActions.Length) throw new Exception("Hold choices differ."); for (int k = 0; k < count; k++) if (modes[k].Text != HoldActions[k]) throw new Exception("Hold action order differs."); }
            bool foundNone = false;
            for (int m = 0; m < count; m++)
            { if (modes[m].Text == "No action") foundNone = true; modes[m].Checked = true; if (cycleShown != (CurrentMode() == "Cycle list")) throw new Exception("Irrelevant cycle controls visible."); }
            if (!foundNone) throw new Exception("No action missing for a gesture.");
        }
        selected = saved; Render();
    }
}

internal sealed class CycleEditor : UserControl
{
    internal event EventHandler Changed;
    private readonly DataGridView grid = new DataGridView();
    internal CycleEditor(List<ToolBinding> tools)
    {
        Size = new Size(540, 238);
        grid.SetBounds(0, 0, 536, 191); grid.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Bottom;
        grid.AllowUserToAddRows = grid.AllowUserToDeleteRows = true; grid.AutoGenerateColumns = false; grid.MultiSelect = false;
        grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect; grid.RowHeadersWidth = 30; grid.BackgroundColor = Color.White; grid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill;
        grid.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "Name", FillWeight = 45 });
        grid.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "Shortcut / output", FillWeight = 35 });
        grid.Columns.Add(new DataGridViewButtonColumn { Text = "Record", UseColumnTextForButtonValue = true, FillWeight = 20 });
        foreach (ToolBinding t in tools) grid.Rows.Add(t.Name, t.Shortcut);
        grid.CellContentClick += delegate(object sender, DataGridViewCellEventArgs e) {
            if (e.RowIndex < 0 || e.ColumnIndex != 2) return;
            using (var d = new CaptureKeyForm(false)) if (d.ShowDialog(this) == DialogResult.OK) {
                if (grid.Rows[e.RowIndex].IsNewRow) grid.Rows.Add("New entry", d.Shortcut); else grid.Rows[e.RowIndex].Cells[1].Value = d.Shortcut;
            }
        };
        grid.CellValueChanged += delegate { Notify(); }; grid.RowsRemoved += delegate { Notify(); }; grid.UserAddedRow += delegate { Notify(); };
        var up = new Button { Text = "Move up", Location = new Point(0, 200), Size = new Size(110, 30), Anchor = AnchorStyles.Left | AnchorStyles.Bottom };
        var down = new Button { Text = "Move down", Location = new Point(120, 200), Size = new Size(110, 30), Anchor = AnchorStyles.Left | AnchorStyles.Bottom };
        var remove = new Button { Text = "Remove", Location = new Point(240, 200), Size = new Size(110, 30), Anchor = AnchorStyles.Left | AnchorStyles.Bottom };
        up.Click += delegate { MoveEntry(-1); }; down.Click += delegate { MoveEntry(1); };
        remove.Click += delegate { if (grid.CurrentRow != null && !grid.CurrentRow.IsNewRow) grid.Rows.Remove(grid.CurrentRow); };
        Controls.AddRange(new Control[] { grid, up, down, remove }); Size = new Size(540, 238);
    }
    private void Notify() { if (Changed != null) Changed(this, EventArgs.Empty); }
    private void MoveEntry(int direction)
    {
        grid.EndEdit(); if (grid.CurrentRow == null || grid.CurrentRow.IsNewRow) return;
        int from = grid.CurrentRow.Index, to = from + direction;
        if (to < 0 || to >= grid.Rows.Count || grid.Rows[to].IsNewRow) return;
        for (int i = 0; i < 2; i++) { object v = grid.Rows[from].Cells[i].Value; grid.Rows[from].Cells[i].Value = grid.Rows[to].Cells[i].Value; grid.Rows[to].Cells[i].Value = v; }
        grid.CurrentCell = grid.Rows[to].Cells[0];
    }
    internal List<ToolBinding> Read()
    {
        grid.EndEdit(); var result = new List<ToolBinding>();
        foreach (DataGridViewRow row in grid.Rows) {
            if (row.IsNewRow) continue;
            string name = Convert.ToString(row.Cells[0].Value).Trim(), key = Convert.ToString(row.Cells[1].Value).Trim();
            if (name.Length != 0 || key.Length != 0) result.Add(new ToolBinding { Name = name, Shortcut = key });
        }
        return result;
    }
    internal void VerifyEditing(string profile)
    {
        grid.Rows[0].Cells[0].Value = profile + " edited"; grid.Rows[0].Cells[1].Value = "F12";
        grid.CurrentCell = grid.Rows[0].Cells[0]; MoveEntry(1);
        List<ToolBinding> read = Read();
        if (read.Count != 20 || read[1].Name != profile + " edited" || read[1].Shortcut != "F12")
            throw new Exception("Inline cycle editing/reordering failed.");
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

