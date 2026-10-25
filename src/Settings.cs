using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Windows.Forms;
using System.Xml;
using System.Xml.Serialization;

public sealed class ToolBinding
{
    public string Name { get; set; }
    public string Shortcut { get; set; }
}

public sealed class ModifierBinding
{
    public bool ReverseScroll { get; set; }
    public int ScrollAmount { get; set; }
    public string DoubleHoldMode { get; set; }
    public string DoubleHoldOutput { get; set; }
    public string HoldMode { get; set; }
    public string HoldOutput { get; set; }
    public string Modifier { get; set; }
    public bool Enabled { get; set; }
    public string NextInput { get; set; }
    public string PreviousInput { get; set; }
    public string TapOutput { get; set; }
    public string HoldNextOutput { get; set; }
    public string HoldPreviousOutput { get; set; }
    public int TapWaitMs { get; set; }
    public int ShortPressMs { get; set; }
    public List<ToolBinding> Tools { get; set; }
}

public sealed class AppSettings
{
    public bool Enabled { get; set; }
    public bool DetectClipStudio { get; set; }
    public List<ModifierBinding> Modifiers { get; set; }

    public List<ToolBinding> Tools { get; set; }
    public static AppSettings Defaults()
    {
        var s = new AppSettings { Enabled = true, DetectClipStudio = true, Modifiers = new List<ModifierBinding>(), Tools = new List<ToolBinding>() };
        foreach (string name in new string[] { "Alt", "Ctrl", "Shift" })
            s.Modifiers.Add(new ModifierBinding { Modifier = name, Enabled = true, NextInput = "]", PreviousInput = "[",
                TapOutput = "B", HoldNextOutput = "F", HoldPreviousOutput = "S", TapWaitMs = 100, ShortPressMs = 300 });
        string[] names = { "Pen", "Sketch", "Blend", "Brush", "Eraser", "Airbrush", "Liquify", "Decoration", "Selection area",
            "Fill", "Auto select", "Gradient", "Operation", "Figure", "Text", "Comic", "Ruler", "Correct line", "Move", "Eyedropper" };
        for (int i = 0; i < names.Length; i++)
            s.Tools.Add(new ToolBinding { Name = names[i], Shortcut = i < 9 ? (i + 1).ToString() : "F" + (i - 8).ToString() });
        s.MigrateCycles();
        return s;
    }
    // Older settings stored one shared list. Copy it once into each profile.
    internal void MigrateCycles()
    {
        if (Modifiers == null) return;
        foreach (ModifierBinding m in Modifiers)
        {
            if (m.ScrollAmount == 0) m.ScrollAmount = 1;
            if (string.IsNullOrEmpty(m.DoubleHoldMode)) m.DoubleHoldMode = "Cycle list";
            if (string.IsNullOrEmpty(m.DoubleHoldOutput)) m.DoubleHoldOutput = "Space";
            if (string.IsNullOrEmpty(m.HoldMode)) m.HoldMode = "Original modifier";
            if (string.IsNullOrEmpty(m.HoldOutput)) m.HoldOutput = m.Modifier;
            if (m.Tools == null || (m.Tools.Count == 0 && Tools != null && Tools.Count > 0))
            {
                m.Tools = new List<ToolBinding>();
                if (Tools != null) foreach (ToolBinding t in Tools)
                    m.Tools.Add(new ToolBinding { Name = t.Name, Shortcut = t.Shortcut });
            }
        }
        Tools = null;
    }
    public bool ShouldSerializeTools() { return Tools != null; }
    public void Validate()
    {
        MigrateCycles();
        if (Modifiers == null || Modifiers.Count != 3) throw new ArgumentException("Config needs Alt, Ctrl, and Shift profiles.");
        var families = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (ModifierBinding m in Modifiers)
        {
            int family = KeyChord.ModifierKey(m.Modifier);
            if (m.DoubleHoldMode != "No action" && m.DoubleHoldMode != "Cycle list" && m.DoubleHoldMode != "Dial scrolling" && m.DoubleHoldMode != "Hold a key")
                throw new ArgumentException(m.Modifier + ": choose a valid tap-hold action.");
            KeyChord.ParseHold(m.DoubleHoldOutput);
            if (m.HoldMode != "No action" && m.HoldMode != "Original modifier" && m.HoldMode != "Cycle list" && m.HoldMode != "Dial scrolling" && m.HoldMode != "Hold a key")
                throw new ArgumentException(m.Modifier + ": choose a valid hold action.");
            KeyChord.ParseHold(m.HoldOutput);
            if (m.ScrollAmount < 1 || m.ScrollAmount > 20) throw new ArgumentException("Scroll amount must be between 1 and 20 notches.");
            if (!families.Add(m.Modifier)) throw new ArgumentException("Duplicate modifier profile: " + m.Modifier);
            KeyChord next = KeyChord.Parse(m.NextInput), previous = KeyChord.Parse(m.PreviousInput);
            if (next.IsNone || previous.IsNone || next.IsWheel || previous.IsWheel || next.Modifiers != 0 || previous.Modifiers != 0 || next.Key == previous.Key)
                throw new ArgumentException(m.Modifier + ": rotation inputs must be two different single keys.");
            if (KeyChord.InFamily(next.Key, family) || KeyChord.InFamily(previous.Key, family))
                throw new ArgumentException(m.Modifier + ": a rotation input cannot be the activation modifier.");
            KeyChord.Parse(m.TapOutput); KeyChord.Parse(m.HoldNextOutput); KeyChord.Parse(m.HoldPreviousOutput);
            if (m.TapWaitMs < 20 || m.TapWaitMs > 2000 || m.ShortPressMs < 20 || m.ShortPressMs > 2000)
                throw new ArgumentException("Timing must be between 20 and 2000 milliseconds.");
            ValidateTools(m.Tools, m.Modifier);
        }

    }
    private static void ValidateTools(List<ToolBinding> Tools, string modifier)
    {
        if (Tools == null || Tools.Count < 1 || Tools.Count > 64) throw new ArgumentException(modifier + " cycle: add between 1 and 64 tools.");
        var shortcuts = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (ToolBinding tool in Tools)
        {
            if (string.IsNullOrWhiteSpace(tool.Name) || !names.Add(tool.Name.Trim())) throw new ArgumentException("Tool names must be nonempty and unique.");
            string chord = KeyChord.Parse(tool.Shortcut).ToString();
            if (!shortcuts.Add(chord)) throw new ArgumentException("Two tools use the same shortcut: " + chord);
        }
    }
    public AppSettings Clone()
    {
        MigrateCycles();
        var serializer = new XmlSerializer(typeof(AppSettings));
        using (var memory = new MemoryStream())
        {
            serializer.Serialize(memory, this); memory.Position = 0;
            return (AppSettings)serializer.Deserialize(memory);
        }
    }
    public static AppSettings Load(string path)
    {
        using (XmlReader reader = XmlReader.Create(path, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null }))
        {
            var result = (AppSettings)new XmlSerializer(typeof(AppSettings)).Deserialize(reader);
            result.Validate(); return result;
        }
    }
    public void Save(string path)
    {
        Validate();
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            using (XmlWriter writer = XmlWriter.Create(temporary, new XmlWriterSettings { Indent = true, Encoding = new UTF8Encoding(false) }))
                new XmlSerializer(typeof(AppSettings)).Serialize(writer, this);
            if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
    internal static void SelfTest()
    {
        AppSettings s = Defaults(); s.Validate();
        foreach (ModifierBinding profile in s.Modifiers) { profile.TapOutput = "No action"; profile.HoldMode = "No action"; profile.DoubleHoldMode = "No action"; }
        AppSettings disabled = s.Clone(); disabled.Validate();
        foreach (ModifierBinding profile in disabled.Modifiers)
            if (!KeyChord.Parse(profile.TapOutput).IsNone || profile.HoldMode != "No action" || profile.DoubleHoldMode != "No action")
                throw new Exception("No action settings round-trip.");
        s = Defaults();
        s.Modifiers[0].HoldMode = "Dial scrolling"; s.Modifiers[0].HoldNextOutput = "Scroll up";
        s.Modifiers[1].DoubleHoldMode = "Hold a key"; s.Modifiers[1].DoubleHoldOutput = "Ctrl";
        s.Modifiers[2].HoldMode = "Hold a key"; s.Modifiers[2].HoldOutput = "Shift+Space";
        s.DetectClipStudio = false; s.Enabled = false;
        s.Modifiers[1].Enabled = false; s.Modifiers[2].TapOutput = "Ctrl+Shift+F4";
        s.Modifiers[0].Tools[0].Shortcut = "Alt+P";
        AppSettings copy = s.Clone(); copy.Validate();
        if (copy.Modifiers[0].HoldMode != "Dial scrolling" || copy.Modifiers[0].HoldNextOutput != "Scroll up" || copy.Modifiers[1].DoubleHoldOutput != "Ctrl" || copy.Modifiers[2].HoldOutput != "Shift+Space")
            throw new Exception("Action/scroll settings round-trip.");
        if (copy.Enabled || copy.DetectClipStudio || copy.Modifiers[1].Enabled || copy.Modifiers[2].TapOutput != "Ctrl+Shift+F4" || copy.Modifiers[0].Tools[0].Shortcut != "Alt+P" || copy.Modifiers[1].Tools[0].Shortcut != "1")
            throw new Exception("Config serialization round-trip.");
        s = Defaults(); s.Modifiers[0].Tools[1].Shortcut = s.Modifiers[0].Tools[0].Shortcut;
        bool rejected = false; try { s.Validate(); } catch (ArgumentException) { rejected = true; }
        if (!rejected) throw new Exception("Duplicate tool shortcuts accepted.");
        s = Defaults(); s.Modifiers[0].NextInput = "Scroll up"; rejected = false;
        try { s.Validate(); } catch (ArgumentException) { rejected = true; }
        if (!rejected) throw new Exception("Scroll accepted as a keyboard input.");
        rejected = false; try { KeyChord.ParseHold("WheelUp"); } catch (ArgumentException) { rejected = true; }
        if (!rejected) throw new Exception("Wheel output accepted as a held key.");
        // Simulate an actual v1.0 XML document with a root Tools list.
        s = Defaults(); s.Tools = s.Modifiers[0].Tools;
        foreach (ModifierBinding profile in s.Modifiers) profile.Tools = null;
        var serializer = new XmlSerializer(typeof(AppSettings));
        using (var memory = new MemoryStream())
        {
            serializer.Serialize(memory, s); memory.Position = 0;
            var migrated = (AppSettings)serializer.Deserialize(memory); migrated.Validate();
            if (migrated.Modifiers[0].Tools.Count != 20 || migrated.Modifiers[1].Tools[19].Shortcut != "F11")
                throw new Exception("Legacy XML migration lost tools.");
            migrated.Modifiers[0].Tools[0].Shortcut = "F12";
            if (migrated.Modifiers[2].Tools[0].Shortcut != "1") throw new Exception("Migrated cycles share objects.");
        }
        using (var xml = new StringWriter())
        {
            serializer.Serialize(xml, Defaults());
            string old = xml.ToString().Replace("</AppSettings>", "<NoModifier><Enabled>true</Enabled><HoldMode>Dial scrolling</HoldMode></NoModifier></AppSettings>");
            using (var reader = new StringReader(old))
            {
                var migrated = (AppSettings)serializer.Deserialize(reader); migrated.Validate();
                using (var saved = new StringWriter())
                { serializer.Serialize(saved, migrated); if (migrated.Modifiers.Count != 3 || saved.ToString().Contains("NoModifier")) throw new Exception("Removed profile migration."); }
            }
        }
        foreach (string text in new string[] { "No action", "B", "Ctrl+Shift+F1", "Alt+Tab", "[", "]", "Space", "Shift+Plus", "Win+Left", "Scroll up", "WheelDown", "Ctrl+Scroll down" })
        {
            KeyChord c = KeyChord.Parse(text), roundTrip = KeyChord.Parse(KeyChord.Parse(text).ToString());
            if (c.Key != roundTrip.Key || c.Modifiers != roundTrip.Modifiers) throw new Exception("Shortcut parsing: " + text);
        }
    }
}

internal sealed class KeyChord
{
    internal const ushort NoAction = 0x102;
    internal bool IsNone { get { return Key == NoAction; } }
    internal const ushort WheelUp = 0x100, WheelDown = 0x101;
    internal bool IsWheel { get { return Key == WheelUp || Key == WheelDown; } }
    internal const int Control = 1, Alt = 2, Shift = 4, Win = 8;
    internal ushort Key;
    internal int WheelNotches = 1;
    internal int Modifiers;
    internal static int ModifierKey(string name)
    {
        if (string.Equals(name, "Alt", StringComparison.OrdinalIgnoreCase)) return 0x12;
        if (string.Equals(name, "Ctrl", StringComparison.OrdinalIgnoreCase)) return 0x11;
        if (string.Equals(name, "Shift", StringComparison.OrdinalIgnoreCase)) return 0x10;
        throw new ArgumentException("Unknown modifier: " + name);
    }
    internal static bool InFamily(int key, int family)
    {
        if (family == 0x12) return key == 0x12 || key == 0xA4 || key == 0xA5;
        if (family == 0x11) return key == 0x11 || key == 0xA2 || key == 0xA3;
        return key == 0x10 || key == 0xA0 || key == 0xA1;
    }
    internal static int FamilyFlag(int family) { return family == 0x12 ? Alt : family == 0x11 ? Control : Shift; }
    internal static KeyChord ParseHold(string text)
    {
        string name = (text ?? "").Trim().ToUpperInvariant();
        ushort modifier = name == "CTRL" || name == "CONTROL" ? (ushort)0xA2 : name == "ALT" ? (ushort)0xA4
            : name == "SHIFT" ? (ushort)0xA0 : name == "WIN" || name == "WINDOWS" ? (ushort)0x5B : (ushort)0;
        if (modifier != 0) return new KeyChord { Key = modifier };
        KeyChord chord = Parse(text);
        if (chord.IsNone) throw new ArgumentException("Choose No action in the action selector instead of the held-key field.");
        if (chord.IsWheel) throw new ArgumentException("A scroll notch cannot be held. Choose Dial scrolling instead.");
        return chord;
    }
    internal static KeyChord Parse(string text)
    {
        if (string.IsNullOrWhiteSpace(text)) throw new ArgumentException("A shortcut cannot be empty.");
        if (text.Trim().Equals("No action", StringComparison.OrdinalIgnoreCase)) return new KeyChord { Key = NoAction };
        string[] parts = text.Trim().Split('+');
        int modifiers = 0;
        for (int i = 0; i < parts.Length - 1; i++)
        {
            string p = parts[i].Trim().ToUpperInvariant(); int flag;
            if (p == "CTRL" || p == "CONTROL") flag = Control;
            else if (p == "ALT") flag = Alt;
            else if (p == "SHIFT") flag = Shift;
            else if (p == "WIN" || p == "WINDOWS") flag = Win;
            else throw new ArgumentException("Unknown shortcut modifier: " + parts[i]);
            if ((modifiers & flag) != 0) throw new ArgumentException("Repeated shortcut modifier.");
            modifiers |= flag;
        }
        string key = parts[parts.Length - 1].Trim();
        ushort vk;
        string wheelName = key.Replace(" ", "").ToUpperInvariant();
        if (wheelName == "WHEELUP" || wheelName == "SCROLLUP") vk = WheelUp;
        else if (wheelName == "WHEELDOWN" || wheelName == "SCROLLDOWN") vk = WheelDown;
        else if (key.Length == 1 && ((key[0] >= 'a' && key[0] <= 'z') || (key[0] >= 'A' && key[0] <= 'Z') || (key[0] >= '0' && key[0] <= '9')))
            vk = char.ToUpperInvariant(key[0]);
        else if (key == "[") vk = 0xDB;
        else if (key == "]") vk = 0xDD;
        else if (key.Equals("Plus", StringComparison.OrdinalIgnoreCase)) vk = 0xBB;
        else if (key.Equals("Minus", StringComparison.OrdinalIgnoreCase)) vk = 0xBD;
        else if (key.Equals("Esc", StringComparison.OrdinalIgnoreCase)) vk = 0x1B;
        else if (key.Equals("CapsLock", StringComparison.OrdinalIgnoreCase)) vk = 0x14;
        else
        {
            Keys parsed;
            if (!Enum.TryParse<Keys>(key, true, out parsed) || (int)parsed <= 0 || (int)parsed > 255)
                throw new ArgumentException("Unknown key '" + key + "'. Examples: B, F1, Space, Ctrl+Shift+F1.");
            vk = (ushort)parsed;
        }
        if (vk == 0x10 || vk == 0x11 || vk == 0x12 || (vk >= 0xA0 && vk <= 0xA5) || vk == 0x5B || vk == 0x5C)
            throw new ArgumentException("Use a key or key combination, rather than a modifier alone. Ordinary holds remain native.");
        if (vk <= 6) throw new ArgumentException("These bindings accept keyboard keys, not mouse buttons.");
        return new KeyChord { Key = vk, Modifiers = modifiers };
    }
    public override string ToString()
    {
        if (IsNone) return "No action";
        string name = Key == 0xA2 ? "Ctrl" : Key == 0xA4 ? "Alt" : Key == 0xA0 ? "Shift" : Key == 0x5B ? "Win"
            : Key == WheelUp ? "Scroll up" : Key == WheelDown ? "Scroll down" : Key == 0xDB ? "[" : Key == 0xDD ? "]" : Key == 0xBB ? "Plus" : Key == 0xBD ? "Minus"
            : Key >= 0x30 && Key <= 0x39 ? ((char)Key).ToString() : ((Keys)Key).ToString();
        return ((Modifiers & Control) != 0 ? "Ctrl+" : "") + ((Modifiers & Alt) != 0 ? "Alt+" : "")
            + ((Modifiers & Shift) != 0 ? "Shift+" : "") + ((Modifiers & Win) != 0 ? "Win+" : "") + name;
    }
}

