using System;
using System.IO;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace AqaSetup {
    internal static class ExistingInstallation {
        public static string Find() {
            string standard = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","AQA-Copilot");
            if (File.Exists(Path.Combine(standard,"aqa-copilot.exe"))) return standard;
            using (RegistryKey root = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall")) {
                if (root != null) foreach (string name in root.GetSubKeyNames()) {
                    if (!name.StartsWith("AQACopilot-",StringComparison.Ordinal)) continue;
                    using (RegistryKey key = root.OpenSubKey(name)) {
                        string path = key == null ? null : key.GetValue("InstallLocation") as string;
                        if (!String.IsNullOrEmpty(path) && File.Exists(Path.Combine(path,"aqa-copilot.exe"))) return path;
                    }
                }
            }
            return null;
        }
        public static string DataDirectory(string appDirectory) {
            string file = Path.Combine(appDirectory,"installation.json");
            if (!File.Exists(file)) return Path.Combine(appDirectory,"data");
            var value = new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(file));
            if (value == null || !value.ContainsKey("data_dir")) throw new ArgumentException("В installation.json не задана папка данных.");
            return InstallConfiguration.Folder(Convert.ToString(value["data_dir"]));
        }
    }
}
