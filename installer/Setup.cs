using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace AqaSetup {
    internal static class Program {
        [STAThread] static int Main(string[] args) {
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            try {
                if(args.Length == 2 && args[0] == "--self-test") { SelfTest.Run(args[1]); return 0; }
                Application.Run(new Wizard()); return 0;
            } catch(Exception error) {
                if(args.Length == 2 && args[0] == "--self-test") { Directory.CreateDirectory(args[1]); File.WriteAllText(Path.Combine(args[1], "FAILED.txt"), error.ToString()); }
                else MessageBox.Show(error.Message, "AQA Copilot Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }

    internal sealed class Wizard : Form {
        static readonly Color Background = Color.FromArgb(19,26,22), Surface = Color.FromArgb(28,39,32), TextColor = Color.FromArgb(225,235,228), Muted = Color.FromArgb(167,188,174), Accent = Color.FromArgb(157,209,170);
        readonly Panel content = new Panel();
        readonly List<Panel> pages = new List<Panel>();
        readonly Label heading = new Label(), subheading = new Label(), steps = new Label();
        readonly Button next = new Button(), back = new Button(), cancel = new Button();
        readonly TextBox appPath = new TextBox(), dataPath = new TextBox(), zipPath = new TextBox(), customModel = new TextBox();
        readonly ComboBox mode = new ComboBox(), model = new ComboBox(), whisper = new ComboBox(), device = new ComboBox();
        readonly CheckBox download = new CheckBox(), shortcut = new CheckBox();
        readonly Label summary = new Label();
        readonly RichTextBox log = new RichTextBox();
        readonly Label state = new Label();
        readonly ProgressBar progress = new ProgressBar();
        readonly object logLock = new object();
        readonly string[] titles = {"Установка AQA Copilot", "Где хранить приложение", "Модели и распознавание", "Всё готово к установке", "Ход установки"};
        int page; bool working, cancelled; string logPath = "", installedDir = ""; OwnedProcess owned;
        readonly JavaScriptSerializer json = new JavaScriptSerializer();
        public Wizard() {
            Text="AQA Copilot · мастер установки"; ClientSize=new Size(960,700); MinimumSize=new Size(976,739); StartPosition=FormStartPosition.CenterScreen;
            Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            BackColor=Background; ForeColor=TextColor; Font=new Font("Segoe UI",10); AutoScaleMode=AutoScaleMode.Dpi;
            Panel rail=new Panel {Dock=DockStyle.Left,Width=190,BackColor=Color.FromArgb(13,20,16)}; Controls.Add(rail);
            Label brand=LabelAt(rail,"aq  Copilot",22,30,160,42,16); brand.ForeColor=Accent;
            LabelAt(rail,"Локальный помощник\nпо QA и AQA",23,82,150,60,10).ForeColor=Muted;
            steps.SetBounds(23,190,155,250); steps.ForeColor=Muted; rail.Controls.Add(steps);
            LabelAt(rail,"Windows x64\nОнлайн-установка\nВерсия 1.1",23,590,150,75,9).ForeColor=Muted;
            Panel body=new Panel {Dock=DockStyle.Fill,Padding=new Padding(30)}; Controls.Add(body); body.BringToFront();
            Panel header=new Panel {Dock=DockStyle.Top,Height=95}; body.Controls.Add(header);
            heading.SetBounds(0,3,680,40); heading.Font=new Font(Font.FontFamily,22,FontStyle.Bold); header.Controls.Add(heading);
            subheading.SetBounds(1,51,670,34); subheading.ForeColor=Muted; header.Controls.Add(subheading);
            Panel footer=new Panel {Dock=DockStyle.Bottom,Height=62}; body.Controls.Add(footer);
            StyleButton(back,"Назад",footer,0,15,100); back.Click+=delegate{ShowPage(page==3 && mode.SelectedIndex==3?1:page-1);};
            StyleButton(cancel,"Отмена",footer,360,15,120); cancel.Anchor=AnchorStyles.Top|AnchorStyles.Right; cancel.Click+=CloseClick;
            StyleButton(next,"Далее →",footer,495,15,185); next.Anchor=AnchorStyles.Top|AnchorStyles.Right; next.BackColor=Accent; next.ForeColor=Background; next.Click+=Next;
            content.Dock=DockStyle.Fill; body.Controls.Add(content); content.BringToFront();
            for(int i=0;i<5;i++){Panel p=new Panel {Dock=DockStyle.Fill,AutoScroll=true}; pages.Add(p); content.Controls.Add(p);}
            BuildWelcome(); BuildFolders(); BuildModels(); BuildSummary(); BuildProgress(); ShowPage(0);
            try { string existing=ExistingInstallation.Find(); if(existing!=null){appPath.Text=existing;dataPath.Text=ExistingInstallation.DataDirectory(existing);mode.SelectedIndex=3;} } catch(Exception) { /* Manual folder selection remains available. */ }
            FormClosing+=OnClosing;
        }
        static Label LabelAt(Control parent,string text,int x,int y,int w,int h,int font=10){Label l=new Label{Text=text,AutoSize=false,Font=new Font("Segoe UI",font),ForeColor=TextColor};l.SetBounds(x,y,w,h);parent.Controls.Add(l);return l;}
        static void StyleButton(Button button,string text,Control parent,int x,int y,int width){button.Text=text;button.SetBounds(x,y,width,36);button.FlatStyle=FlatStyle.Flat;button.FlatAppearance.BorderColor=Color.FromArgb(67,89,74);button.BackColor=Surface;button.ForeColor=TextColor;parent.Controls.Add(button);}
        static void Edit(TextBox box,Control parent,int y,int width=570){box.SetBounds(0,y,width,29);box.BackColor=Surface;box.ForeColor=TextColor;box.BorderStyle=BorderStyle.FixedSingle;parent.Controls.Add(box);}
        static void Choose(ComboBox box,Control parent,int y,object[] values,int width=670){box.SetBounds(0,y,width,32);box.DropDownStyle=ComboBoxStyle.DropDownList;box.BackColor=Surface;box.ForeColor=TextColor;box.Items.AddRange(values);box.SelectedIndex=0;parent.Controls.Add(box);}
        static void Check(CheckBox box,Control parent,string text,int y){box.Text=text;box.SetBounds(0,y,670,30);box.ForeColor=TextColor;parent.Controls.Add(box);}
        void BuildWelcome(){
            Panel p=pages[0];LabelAt(p,"Приложение, модели и настройки — в одном мастере.",0,0,670,35,13);
            LabelAt(p,"Выберите способ установки",0,58,670,26);
            Choose(mode,p,90,new object[]{"Собрать и установить из встроенных исходников","Установить готовую сборку из ZIP","Настроить модели у установленного приложения","Обновить приложение — сохранить данные и модели"});
            LabelAt(p,"Сборка из исходников скачает Python, Node.js, Rust и C++ Build Tools, если их нет. Это может занять продолжительное время и потребовать разрешения Windows. Готовый ZIP позволяет пропустить сборку.",0,145,670,100).ForeColor=Muted;
            LabelAt(p,"Нужны интернет и свободное место. Для первой сборки разумно оставить 30–50 ГБ, дополнительно — место под выбранные модели.\n\nOllama устанавливается локально, без системной службы. Ничего не начнётся до нажатия «Установить».",0,260,670,145).ForeColor=Muted;
        }
        void BrowseFolder(TextBox field){using(FolderBrowserDialog dialog=new FolderBrowserDialog{SelectedPath=field.Text,Description="Выберите локальную папку"})if(dialog.ShowDialog(this)==DialogResult.OK)field.Text=dialog.SelectedPath;}
        void BuildFolders(){
            Panel p=pages[1];LabelAt(p,"Папка приложения",0,0,670,28);Edit(appPath,p,32);
            appPath.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","AQA-Copilot");
            Button browse=new Button();StyleButton(browse,"Обзор…",p,580,29,90);browse.Click+=delegate{BrowseFolder(appPath);};
            LabelAt(p,"Модели, история и настройки",0,85,670,28);Edit(dataPath,p,117);dataPath.Text=Path.Combine(appPath.Text,"data");
            string old=appPath.Text;appPath.TextChanged+=delegate{if(dataPath.Text==Path.Combine(old,"data"))dataPath.Text=Path.Combine(appPath.Text,"data");old=appPath.Text;};
            Button dataBrowse=new Button();StyleButton(dataBrowse,"Обзор…",p,580,114,90);dataBrowse.Click+=delegate{BrowseFolder(dataPath);};
            LabelAt(p,"Архив готового приложения (только для установки из ZIP)",0,175,670,28);Edit(zipPath,p,207);
            Button zipBrowse=new Button();StyleButton(zipBrowse,"ZIP…",p,580,204,90);zipBrowse.Click+=delegate{using(OpenFileDialog dialog=new OpenFileDialog{Filter="AQA Copilot ZIP|*.zip"})if(dialog.ShowDialog(this)==DialogResult.OK)zipPath.Text=dialog.FileName;};
            LabelAt(p,"Можно хранить модели на другом диске. При повторной настройке мастер сохранит историю, создаст резервную копию настроек и применит выбранную модель.\n\nZIP должен быть новой сборкой с поддержкой выбора моделей; старые архивы будут отклонены.",0,275,670,130).ForeColor=Muted;
        }
        void BuildModels(){
            Panel p=pages[2];Check(download,p,"Скачать выбранные модели после установки",0);download.Checked=true;
            LabelAt(p,"Модель ответа",0,45,670,25);
            Choose(model,p,72,new object[]{"Qwen3 1.7B — компактная · загрузка ≈ 1,4 ГБ","Qwen3 4B — средняя · загрузка ≈ 2,5 ГБ","Qwen3 8B — крупнее · загрузка ≈ 5,2 ГБ","Qwen3 14B — крупная · загрузка ≈ 9,3 ГБ","Другая локальная модель Ollama"});model.SelectedIndex=1;
            Edit(customModel,p,113,670);customModel.Text="qwen3:4b";
            model.SelectedIndexChanged+=delegate{customModel.Enabled=model.SelectedIndex==4;if(model.SelectedIndex<4)customModel.Text=new[]{"qwen3:1.7b","qwen3:4b","qwen3:8b","qwen3:14b"}[model.SelectedIndex];};customModel.Enabled=false;
            Button catalog=new Button();StyleButton(catalog,"Каталог моделей Ollama ↗",p,0,155,280);catalog.Click+=delegate{try{Process.Start(new ProcessStartInfo("https://ollama.com/library"){UseShellExecute=true});}catch(Exception e){MessageBox.Show(this,e.Message);}};
            Button installed=new Button();StyleButton(installed,"Уже установленные…",p,295,155,260);installed.Click+=async delegate{installed.Enabled=false;try{await InstalledModels();}catch(Exception error){MessageBox.Show(this,error.Message);}finally{installed.Enabled=true;}};
            LabelAt(p,"В каталоге выберите локальную chat-модель, скопируйте её тег или команду ollama run. Embedding- и cloud-модели для ответов не подходят. Существующая модель будет подготовлена в отдельной папке приложения.",0,204,670,65,9).ForeColor=Muted;
            LabelAt(p,"Распознавание речи (Whisper)",0,282,350,25);Choose(whisper,p,310,new object[]{"tiny — минимальная","base — компактная","small — баланс","medium — выше качество","large-v3 — больше ресурсов"},380);whisper.SelectedIndex=2;
            LabelAt(p,"Вычисления распознавания",400,282,270,25);Choose(device,p,310,new object[]{"CPU — без NVIDIA","CUDA — NVIDIA GPU"},270);device.Left=400;
            LabelAt(p,"Размер загрузки не равен расходу RAM/VRAM. CUDA требует подходящей NVIDIA и драйвера; CPU доступнее, но медленнее. Модель ответа использует автоматический выбор устройства Ollama.",0,355,670,60,9).ForeColor=Muted;
            Check(shortcut,p,"Создать ярлык на рабочем столе",427);shortcut.Checked=true;
        }
        async Task InstalledModels(){
            List<string> names=await Task.Run(delegate{
                HashSet<string> found=new HashSet<string>();
                foreach(int port in new[]{11434,11435})try{
                    HttpWebRequest request=(HttpWebRequest)WebRequest.Create("http://127.0.0.1:"+port+"/api/tags");request.Proxy=null;request.Timeout=2500;request.ReadWriteTimeout=2500;
                    using(WebResponse response=request.GetResponse())using(StreamReader reader=new StreamReader(response.GetResponseStream())){
                        foreach(string name in ParseLocalModels(reader.ReadToEnd()))found.Add(name);
                    }
                }catch(WebException){}catch(ArgumentException){}
                return found.OrderBy(x=>x).ToList();
            });
            if(names.Count==0){MessageBox.Show(this,"Нет доступных локальных моделей. Запустите Ollama с её API либо откройте каталог и скопируйте тег. Мастер не запускает Ollama при просмотре списка.","Модели Ollama");return;}
            using(Form picker=new Form{Text="Локальные модели Ollama",ClientSize=new Size(520,350),StartPosition=FormStartPosition.CenterParent,BackColor=Background,ForeColor=TextColor}){
                ListBox list=new ListBox{Dock=DockStyle.Fill,BackColor=Surface,ForeColor=TextColor,Font=Font};list.Items.AddRange(names.ToArray());list.SelectedIndex=0;
                Button select=new Button{Text="Выбрать",Dock=DockStyle.Bottom,Height=44,DialogResult=DialogResult.OK};picker.Controls.Add(list);picker.Controls.Add(select);picker.AcceptButton=select;
                if(picker.ShowDialog(this)==DialogResult.OK){model.SelectedIndex=4;customModel.Text=(string)list.SelectedItem;}
            }
        }
        internal static List<string> ParseLocalModels(string text){
            Dictionary<string,object> payload=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(text);List<string> result=new List<string>();
            if(!payload.ContainsKey("models"))return result;
            foreach(object value in (IEnumerable)payload["models"]){
                Dictionary<string,object> item=value as Dictionary<string,object>;if(item==null || !item.ContainsKey("name"))continue;
                if((item.ContainsKey("remote_host") && !String.IsNullOrEmpty(Convert.ToString(item["remote_host"]))) || (item.ContainsKey("remote_model") && !String.IsNullOrEmpty(Convert.ToString(item["remote_model"]))))continue;
                Dictionary<string,object> details=item.ContainsKey("details")?item["details"] as Dictionary<string,object>:null;
                if(details==null || !details.ContainsKey("format") || Convert.ToString(details["format"])!="gguf")continue;
                try{result.Add(InstallConfiguration.NormalizeModel(Convert.ToString(item["name"])));}catch(ArgumentException){}
            }
            return result;
        }
        void BuildSummary(){summary.AutoSize=true;summary.MaximumSize=new Size(660,0);summary.BackColor=Background;summary.ForeColor=TextColor;summary.Font=new Font("Segoe UI",11);pages[3].Controls.Add(summary);}
        void BuildProgress(){Panel p=pages[4];state.SetBounds(0,0,670,48);state.ForeColor=Accent;p.Controls.Add(state);progress.SetBounds(0,54,670,12);p.Controls.Add(progress);log.SetBounds(0,88,670,365);log.ReadOnly=true;log.BackColor=Color.FromArgb(12,18,14);log.ForeColor=Muted;log.Font=new Font("Consolas",9);log.WordWrap=true;p.Controls.Add(log);}
        InstallConfiguration Collect(){return new InstallConfiguration{app_dir=appPath.Text,data_dir=dataPath.Text,install_mode=new[]{"source","archive","models","update"}[mode.SelectedIndex],archive=zipPath.Text,model=InstallConfiguration.NormalizeModel(customModel.Text),asr_model=new[]{"tiny","base","small","medium","large-v3"}[whisper.SelectedIndex],device=device.SelectedIndex==0?"cpu":"cuda",prepare_models=mode.SelectedIndex!=3 && download.Checked,shortcut=shortcut.Checked};}
        internal void ShowPage(int index){
            page=index;for(int i=0;i<pages.Count;i++)pages[i].Visible=i==page;pages[page].BringToFront();heading.Text=titles[page];
            subheading.Text=page==4?"Можно следить за этапами и журналом ниже.":"Шаг "+(page+1)+" из 4 · До подтверждения ничего не устанавливается";
            steps.Text=String.Join("\n\n",new[]{"1   Способ установки","2   Папки","3   Модели","4   Подтверждение"}.Select((s,i)=>(i==page?"●  ":"    ")+s));
            back.Visible=page>0 && page<4;next.Text=page==3?(mode.SelectedIndex==3?"Обновить":"Установить"):"Далее →";
            if(page==1){dataPath.ReadOnly=mode.SelectedIndex==3;zipPath.Enabled=mode.SelectedIndex==1;}
            if(page==3){InstallConfiguration c=Collect();summary.Text="Приложение\n"+c.app_dir+"\n\nМодели и история\n"+c.data_dir+"\n\nСпособ: "+mode.Text+"\nМодель ответа: "+c.model+"\nРечь: Whisper "+c.asr_model+" / "+c.device.ToUpperInvariant()+"\nЗагрузить модели: "+(c.prepare_models?"да":"нет, настроить позже")+"\nЯрлык: "+(c.shortcut?"да":"нет")+"\n\nСуществующая история сохраняется. Настройки выбранных моделей будут обновлены с резервной копией.\n\nПри сборке из исходников мастер загрузит недостающие инструменты. Windows может запросить права администратора. Приложение после установки не запускается автоматически.";}
            if(page==3 && mode.SelectedIndex==3) summary.Text="Обновление AQA Copilot\n\n"+appPath.Text+"\n\nДанные остаются в папке\n"+dataPath.Text+"\n\nМодели, история, настройки и ярлыки сохраняются. Повторного скачивания моделей не будет.\n\nНовая версия собирается из встроенных исходников, затем заменяет файлы программы. Недостающие инструменты сборки будут загружены. Предыдущие файлы сохраняются в .setup/backups.\n\nПеред обновлением закройте приложение через «Выход» в меню трея. При принудительном прерывании замены повторите обновление.";
        }
        internal void PreviewUpdate(string directory) {
            appPath.Text=directory;dataPath.Text=ExistingInstallation.DataDirectory(directory);mode.SelectedIndex=3;
            Collect().Validate();ShowPage(3);
        }
        async void Next(object sender,EventArgs e){
            try{
                if(page==4){if(!working)Close();return;}
                if(page==1){InstallConfiguration c=Collect();c.Validate();if(c.install_mode=="update"){dataPath.Text=ExistingInstallation.DataDirectory(c.app_dir);ShowPage(3);return;}}
                if(page==2){Collect().Validate();}
                if(page<3){ShowPage(page+1);return;}
                InstallConfiguration configuration=Collect();configuration.Validate();installedDir=configuration.app_dir;
                ShowPage(4);working=true;cancelled=false;next.Enabled=false;back.Visible=false;cancel.Text="Прервать";state.Text="Подготовка…";progress.Style=ProgressBarStyle.Marquee;
                try{await Task.Run(delegate{RunInstallation(configuration);});state.Text="Установка завершена. Приложение можно открыть из выбранной папки.";progress.Style=ProgressBarStyle.Continuous;progress.Value=100;}
                catch(Exception error){state.Text=cancelled?"Установка прервана. Загруженные файлы сохранены.":"Установка не завершена. Причина записана в журнал.";AppendLog(error.ToString());progress.Style=ProgressBarStyle.Continuous;progress.Value=0;}
                finally{working=false;if(owned!=null){owned.Dispose();owned=null;}next.Enabled=true;next.Text="Закрыть";cancel.Text="Открыть папку";cancel.Click-=CloseClick;cancel.Click+=OpenFolder;}
            }catch(Exception error){MessageBox.Show(this,error.Message,"Проверьте параметры",MessageBoxButtons.OK,MessageBoxIcon.Information);}
        }
        void CloseClick(object sender,EventArgs e){Close();}
        void OpenFolder(object sender,EventArgs e){if(Directory.Exists(installedDir))Process.Start(new ProcessStartInfo(installedDir){UseShellExecute=true});}
        void OnClosing(object sender,FormClosingEventArgs e){
            if(!working)return;
            e.Cancel=true;
            if(MessageBox.Show(this,"Прервать установку? Загруженные файлы сохранятся. Уже запущенные системные установщики могут завершиться отдельно.","AQA Copilot",MessageBoxButtons.YesNo)!=DialogResult.Yes)return;
            cancelled=true;state.Text="Прерывание…";if(owned!=null){owned.Dispose();owned=null;}
        }
        void AppendLog(string line){
            if(String.IsNullOrEmpty(line))return;
            lock(logLock){if(logPath.Length>0)File.AppendAllText(logPath,line+Environment.NewLine,new UTF8Encoding(false));}
            if(!IsDisposed && IsHandleCreated)BeginInvoke((Action)delegate{if(log.TextLength>160000)log.Text=log.Text.Substring(log.TextLength-80000);log.AppendText(line+Environment.NewLine);log.SelectionStart=log.TextLength;log.ScrollToCaret();if(line.StartsWith("STAGE:"))state.Text=line.Substring(6).Trim();});
        }
        internal static string ExtractSource(string destination){
            string root=Path.GetFullPath(destination);Directory.CreateDirectory(root);
            using(Stream stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("source.zip")){
                if(stream==null)throw new InvalidOperationException("В установщике отсутствует архив исходников.");
                using(ZipArchive zip=new ZipArchive(stream,ZipArchiveMode.Read)){
                    foreach(ZipArchiveEntry entry in zip.Entries){
                        string target=Path.GetFullPath(Path.Combine(root,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));
                        if(!target.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("Некорректный путь в архиве.");
                        Directory.CreateDirectory(Path.GetDirectoryName(target));if(entry.Name.Length>0)entry.ExtractToFile(target,true);
                    }
                }
            }
            return Path.Combine(root,"AqaCopilot");
        }
        internal static string Quote(string value) {
            StringBuilder result = new StringBuilder("\""); int slashes = 0;
            foreach(char c in value) {
                if(c == '\\') { slashes++; continue; }
                if(c == '"') result.Append('\\', slashes * 2 + 1).Append(c);
                else result.Append('\\', slashes).Append(c);
                slashes = 0;
            }
            return result.Append('\\', slashes * 2).Append('"').ToString();
        }
        void RunInstallation(InstallConfiguration config){
            string staging=Path.Combine(config.app_dir,".setup","runs",DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,8));
            Directory.CreateDirectory(staging);logPath=Path.Combine(staging,"setup.log");AppendLog("AQA Copilot setup. No application inference is run by this wizard.");
            string source=ExtractSource(Path.Combine(staging,"source"));string configuration=Path.Combine(staging,"options.json");string gate=Path.Combine(staging,"start.gate");
            File.WriteAllText(configuration,json.Serialize(config),new UTF8Encoding(false));
            ProcessStartInfo info=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe"));
            info.Arguments="-NoProfile -ExecutionPolicy Bypass -File "+Quote(Path.Combine(source,"installer","Install.ps1"))+" -ConfigPath "+Quote(configuration)+" -StartGate "+Quote(gate);
            info.UseShellExecute=false;info.CreateNoWindow=true;info.WindowStyle=ProcessWindowStyle.Hidden;info.RedirectStandardOutput=true;info.RedirectStandardError=true;info.StandardOutputEncoding=Encoding.UTF8;info.StandardErrorEncoding=Encoding.UTF8;
            using(Process process=new Process{StartInfo=info}){
                process.OutputDataReceived+=delegate(object s,DataReceivedEventArgs e){AppendLog(e.Data);};process.ErrorDataReceived+=delegate(object s,DataReceivedEventArgs e){AppendLog(e.Data);};
                process.Start();try{owned=new OwnedProcess(process);}catch{try{process.Kill();}catch{}throw;}
                process.BeginOutputReadLine();process.BeginErrorReadLine();
                if(cancelled){owned.Dispose();throw new OperationCanceledException();}
                File.WriteAllText(gate,"start");process.WaitForExit();
                if(cancelled)throw new OperationCanceledException("Cancelled by user");
                if(process.ExitCode!=0)throw new InvalidOperationException("Ошибка установщика, код "+process.ExitCode+". Журнал: "+logPath);
                if(!File.Exists(Path.Combine(config.app_dir,"aqa-copilot.exe")))throw new InvalidOperationException("Процесс завершился без файла приложения.");
            }
        }
    }
    internal static class SelfTest {
        public static void Run(string destination){
            Directory.CreateDirectory(destination);
            if(InstallConfiguration.NormalizeModel("ollama run qwen3:4b")!="qwen3:4b")throw new Exception("Model parsing failed");
            foreach(string invalid in new[]{"qwen3:cloud","x;calc:latest","../model:x","a:4b & whoami"}){
                bool rejected=false;try{InstallConfiguration.NormalizeModel(invalid);}catch(ArgumentException){rejected=true;}if(!rejected)throw new Exception("Unsafe model accepted");
            }
            List<string> models=Wizard.ParseLocalModels("{\"models\":[{\"name\":\"qwen3:4b\",\"details\":{\"format\":\"gguf\"}},{\"name\":\"x:cloud\",\"remote_host\":\"https://example.test\",\"details\":{\"format\":\"gguf\"}}]}");
            if(models.Count!=1 || models[0]!="qwen3:4b")throw new Exception("Local catalog filter failed");
            InstallConfiguration unsafeConfig=new InstallConfiguration{app_dir=Path.Combine(destination,"app"),data_dir=Path.Combine(destination,"app","resources","private"),model="qwen3:4b",install_mode="source",asr_model="small",device="cpu"};
            bool unsafeRejected=false;try{unsafeConfig.Validate();}catch(ArgumentException){unsafeRejected=true;}if(!unsafeRejected)throw new Exception("Unsafe data folder accepted");
            using(Process worker=Process.Start(new ProcessStartInfo("powershell.exe","-NoProfile -Command Start-Sleep -Seconds 30"){UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden})){
                using(OwnedProcess job=new OwnedProcess(worker)) { }
                if(!worker.WaitForExit(5000)){worker.Kill();throw new Exception("Owned worker did not stop");}
            }
            string source=Wizard.ExtractSource(Path.Combine(destination,"payload"));
            if(!File.Exists(Path.Combine(source,"Setup.ps1")) || !File.Exists(Path.Combine(source,"installer","Install.ps1")))throw new Exception("Payload incomplete");
            using(Wizard form=new Wizard()){
                form.ShowInTaskbar=false;form.Opacity=0;form.Show();
                for(int page=0;page<4;page++){form.ShowPage(page);Application.DoEvents();using(Bitmap bitmap=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,form.Size));bitmap.Save(Path.Combine(destination,"step-"+page+".png"));}}
                string existing=Path.Combine(destination,"existing");Directory.CreateDirectory(existing);File.WriteAllText(Path.Combine(existing,"aqa-copilot.exe"),"fixture");
                File.WriteAllText(Path.Combine(existing,"installation.json"),new JavaScriptSerializer().Serialize(new {data_dir=Path.Combine(destination,"external-data")}));
                form.PreviewUpdate(existing);Application.DoEvents();using(Bitmap bitmap=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,form.Size));bitmap.Save(Path.Combine(destination,"update.png"));}
                form.Close();
            }
            File.WriteAllText(Path.Combine(destination,"PASS.txt"),"PASS: model validation, local catalog parsing, embedded source extraction, four wizard pages. No installs, network requests or model downloads.");
        }
    }
}
