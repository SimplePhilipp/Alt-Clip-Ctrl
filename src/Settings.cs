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
    public string Modifier { get; set; }
    public bool Enabled { get; set; }
    public string NextInput { get; set; }
    public string PreviousInput { get; set; }
    public string TapOutput { get; set; }
    public string HoldNextOutput { get; set; }
    public string HoldPreviousOutput { get; set; }
    public int TapWaitMs { get; set; }
    public int ShortPressMs { get; set; }
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
        return s;
    }
    public void Validate()
    {
        if (Modifiers == null || Modifiers.Count != 3) throw new ArgumentException("Config needs Alt, Ctrl, and Shift profiles.");
        var families = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (ModifierBinding m in Modifiers)
        {
            int family = KeyChord.ModifierKey(m.Modifier);
            if (!families.Add(m.Modifier)) throw new ArgumentException("Duplicate modifier profile: " + m.Modifier);
            KeyChord next = KeyChord.Parse(m.NextInput), previous = KeyChord.Parse(m.PreviousInput);
            if (next.Modifiers != 0 || previous.Modifiers != 0 || next.Key == previous.Key)
                throw new ArgumentException(m.Modifier + ": rotation inputs must be two different single keys.");
            if (KeyChord.InFamily(next.Key, family) || KeyChord.InFamily(previous.Key, family))
                throw new ArgumentException(m.Modifier + ": a rotation input cannot be the activation modifier.");
            KeyChord.Parse(m.TapOutput); KeyChord.Parse(m.HoldNextOutput); KeyChord.Parse(m.HoldPreviousOutput);
            if (m.TapWaitMs < 20 || m.TapWaitMs > 2000 || m.ShortPressMs < 20 || m.ShortPressMs > 2000)
                throw new ArgumentException("Timing must be between 20 and 2000 milliseconds.");
        }
        if (Tools == null || Tools.Count < 1 || Tools.Count > 64) throw new ArgumentException("Add between 1 and 64 tools.");
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
        s.DetectClipStudio = false; s.Enabled = false;
        s.Modifiers[1].Enabled = false; s.Modifiers[2].TapOutput = "Ctrl+Shift+F4";
        s.Tools[0].Shortcut = "Alt+P";
        AppSettings copy = s.Clone(); copy.Validate();
        if (copy.Enabled || copy.DetectClipStudio || copy.Modifiers[1].Enabled || copy.Modifiers[2].TapOutput != "Ctrl+Shift+F4" || copy.Tools[0].Shortcut != "Alt+P")
            throw new Exception("Config serialization round-trip.");
        s = Defaults(); s.Tools[1].Shortcut = s.Tools[0].Shortcut;
        bool rejected = false; try { s.Validate(); } catch (ArgumentException) { rejected = true; }
        if (!rejected) throw new Exception("Duplicate tool shortcuts accepted.");
        foreach (string text in new string[] { "B", "Ctrl+Shift+F1", "Alt+Tab", "[", "]", "Space", "Shift+Plus", "Win+Left" })
        {
            KeyChord c = KeyChord.Parse(text), roundTrip = KeyChord.Parse(KeyChord.Parse(text).ToString());
            if (c.Key != roundTrip.Key || c.Modifiers != roundTrip.Modifiers) throw new Exception("Shortcut parsing: " + text);
        }
    }
}

internal sealed class KeyChord
{
    internal const int Control = 1, Alt = 2, Shift = 4, Win = 8;
    internal ushort Key;
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
    internal static KeyChord Parse(string text)
    {
        if (string.IsNullOrWhiteSpace(text)) throw new ArgumentException("A shortcut cannot be empty.");
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
        if (key.Length == 1 && ((key[0] >= 'a' && key[0] <= 'z') || (key[0] >= 'A' && key[0] <= 'Z') || (key[0] >= '0' && key[0] <= '9')))
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
        string name = Key == 0xDB ? "[" : Key == 0xDD ? "]" : Key == 0xBB ? "Plus" : Key == 0xBD ? "Minus"
            : Key >= 0x30 && Key <= 0x39 ? ((char)Key).ToString() : ((Keys)Key).ToString();
        return ((Modifiers & Control) != 0 ? "Ctrl+" : "") + ((Modifiers & Alt) != 0 ? "Alt+" : "")
            + ((Modifiers & Shift) != 0 ? "Shift+" : "") + ((Modifiers & Win) != 0 ? "Win+" : "") + name;
    }
}

