using System;
using System.IO;
using System.Text.RegularExpressions;

namespace AqaSetup {
    public sealed class InstallConfiguration {
        public string app_dir { get; set; }
        public string data_dir { get; set; }
        public string install_mode { get; set; }
        public string archive { get; set; }
        public string model { get; set; }
        public string asr_model { get; set; }
        public string device { get; set; }
        public bool prepare_models { get; set; }
        public bool shortcut { get; set; }

        public static string NormalizeModel(string text) {
            text = text.Trim();
            if (text.StartsWith("ollama run ", StringComparison.OrdinalIgnoreCase)) text = text.Substring(11).Trim();
            if (!text.Contains(":")) text += ":latest";
            if (text.Length > 160 || text.IndexOf("cloud", StringComparison.OrdinalIgnoreCase) >= 0 ||
                !Regex.IsMatch(text, @"^[a-zA-Z0-9][a-zA-Z0-9_.-]*(/[a-zA-Z0-9][a-zA-Z0-9_.-]*)?:[a-zA-Z0-9][a-zA-Z0-9_.-]*$"))
                throw new ArgumentException("Введите тег локальной модели, например qwen3:4b. Облачные модели не поддерживаются.");
            return text;
        }
        public static string Folder(string value) {
            if (String.IsNullOrWhiteSpace(value) || !Path.IsPathRooted(value) || value.StartsWith(@"\\") || value.Contains("\""))
                throw new ArgumentException("Выберите абсолютный путь к локальной папке.");
            string path = Path.GetFullPath(value).TrimEnd('\\');
            if (path.Length <= 3 || String.Equals(path, Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), StringComparison.OrdinalIgnoreCase) ||
                String.Equals(path, Environment.GetFolderPath(Environment.SpecialFolder.Windows), StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("Выберите отдельную папку приложения, не корень диска или системную папку.");
            return path;
        }
        public void Validate() {
            if (install_mode == "update") {
                app_dir = Folder(app_dir);
                if (!File.Exists(Path.Combine(app_dir,"aqa-copilot.exe"))) throw new ArgumentException("Выберите папку уже установленного AQA Copilot.");
                return;
            }
            app_dir = Folder(app_dir); data_dir = Folder(data_dir); model = NormalizeModel(model);
            foreach(string reserved in new[]{app_dir, Path.Combine(app_dir,"resources"), Path.Combine(app_dir,".setup")}) {
                if(String.Equals(data_dir,reserved,StringComparison.OrdinalIgnoreCase) ||
                    (reserved != app_dir && data_dir.StartsWith(reserved+"\\",StringComparison.OrdinalIgnoreCase)))
                    throw new ArgumentException("Храните данные в отдельной папке data или на другом диске, не в resources/.setup и не в корне приложения.");
            }
            if (install_mode != "source" && install_mode != "archive" && install_mode != "models") throw new ArgumentException("Неизвестный режим установки.");
            if (install_mode == "archive" && !File.Exists(archive)) throw new ArgumentException("Выберите готовый ZIP приложения.");
            if (install_mode == "models" && !File.Exists(Path.Combine(app_dir, "aqa-copilot.exe"))) throw new ArgumentException("В выбранной папке нет aqa-copilot.exe.");
            if (!Regex.IsMatch(asr_model, @"^(tiny|base|small|medium|large-v3)$") || (device != "cpu" && device != "cuda")) throw new ArgumentException("Неверные параметры распознавания речи.");
        }
    }
}
