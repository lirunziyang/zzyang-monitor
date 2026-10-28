using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Zzyang
{
    internal static class Program
    {
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr FindWindow(string lpClassName, string lpWindowName);

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

        [DllImport("dwmapi.dll")]
        private static extern int DwmExtendFrameIntoClientArea(IntPtr hwnd, ref MARGINS margins);


        [DllImport("user32.dll")]
        private static extern int SetWindowCompositionAttribute(IntPtr hwnd, ref WINCOMPDATA data);

        [StructLayout(LayoutKind.Sequential)]
        private struct MARGINS { public int Left, Right, Top, Bottom; }

        [StructLayout(LayoutKind.Sequential)]
        private struct ACCENTPOLICY
        {
            public int AccentState;
            public int AccentFlags;
            public int GradientColor;
            public int AnimationId;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct WINCOMPDATA
        {
            public int Attribute;
            public IntPtr Data;
            public int SizeOfData;
        }

        private const int SW_RESTORE = 9;

        /// 让窗口背后透出桌面（Win11 用系统亚克力，Win10 用 ACCENT 回退）
        private static void EnableGlass(Form form)
        {
            try
            {
                IntPtr hwnd = form.Handle;
                int dark = 1;
                DwmSetWindowAttribute(hwnd, 20, ref dark, sizeof(int));   // 深色标题栏
                // 只做深色标题栏；窗口本身保持不透明，避免 WebView2 透明背景导致渲染空白
            }
            catch (Exception) { }
        }
        private const int EXIT_ALREADY_RUNNING = 42;

        private static string PidFile(string dataDir)
        {
            return Path.Combine(dataDir, "host.pid");
        }

        private static bool IsOurs(uint pid, out string pname)
        {
            pname = "?";
            try
            {
                pname = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName;
                return pname.Equals("ZzyangMonitor", StringComparison.OrdinalIgnoreCase);
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static IntPtr FindWindowOfProcess(uint pid)
        {
            IntPtr found = IntPtr.Zero;
            EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)
            {
                uint owner;
                GetWindowThreadProcessId(hWnd, out owner);
                if (owner == pid)
                {
                    found = hWnd;
                    return false;
                }
                return true;
            }, IntPtr.Zero);
            return found;
        }

        [STAThread]
        private static void Main(string[] args)
        {
            string url = args.Length > 0 ? args[0] : "about:blank";
            string dir = AppDomain.CurrentDomain.BaseDirectory;
            string dataDir = args.Length > 1 ? args[1] : Path.Combine(dir, "data");
            bool trayMode = args.Length > 2 && args[2].Equals("tray", StringComparison.OrdinalIgnoreCase);

            string hostLog = Path.Combine(dataDir, "host.log");
            Action<string> note = delegate(string msg)
            {
                try
                {
                    Directory.CreateDirectory(dataDir);
                    File.AppendAllText(hostLog,
                        DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + msg + Environment.NewLine);
                }
                catch (Exception) { }
            };

            note("启动 pid=" + System.Diagnostics.Process.GetCurrentProcess().Id + " url=" + url);

            // 只看「本程序自己的进程」有没有窗口，靠标题找会被幽灵窗口/浏览器页面骗到
            uint otherPid = 0;
            try
            {
                string pf = PidFile(dataDir);
                if (File.Exists(pf))
                {
                    string text = File.ReadAllText(pf).Trim();
                    otherPid = uint.Parse(text);
                }
            }
            catch (Exception) { }

            string otherName;
            if (otherPid != 0 && otherPid != (uint)System.Diagnostics.Process.GetCurrentProcess().Id
                && IsOurs(otherPid, out otherName))
            {
                IntPtr target = FindWindowOfProcess(otherPid);
                note("发现已有实例 pid=" + otherPid + " 窗口=" + target);
                if (target != IntPtr.Zero)
                {
                    ShowWindow(target, SW_RESTORE);
                    SetForegroundWindow(target);
                    Environment.Exit(EXIT_ALREADY_RUNNING);
                }
            }
            note("没有可用的已有窗口，创建新窗口");

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            Form form = new Form();
            form.Text = "大肥鱼监测";
            form.BackColor = Color.FromArgb(10, 12, 14);
            form.StartPosition = FormStartPosition.CenterScreen;
            form.Width = 1240;
            form.Height = 860;
            form.MinimumSize = new Size(960, 620);
            form.ShowInTaskbar = true;

            string ico = Path.Combine(dir, "app.ico");
            if (File.Exists(ico))
            {
                try { form.Icon = new Icon(ico); }
                catch (Exception) { }
            }

            string statePath = Path.Combine(dataDir, "window.txt");
            try
            {
                if (File.Exists(statePath))
                {
                    string[] p = File.ReadAllText(statePath).Split(',');
                    if (p.Length == 4)
                    {
                        int x = int.Parse(p[0]);
                        int y = int.Parse(p[1]);
                        int w = int.Parse(p[2]);
                        int h = int.Parse(p[3]);
                        if (w >= 960 && h >= 620)
                        {
                            form.StartPosition = FormStartPosition.Manual;
                            form.Bounds = new Rectangle(x, y, w, h);
                        }
                    }
                }
            }
            catch (Exception) { }

            WebView2 web = new WebView2();
            web.Dock = DockStyle.Fill;
            try
            {
                string udf = Path.Combine(dataDir, "webview");
                Directory.CreateDirectory(udf);
                web.CreationProperties = new CoreWebView2CreationProperties();
                // 关掉 GPU 合成：个别机器/驱动上 WebView2 会整块黑屏
                web.CreationProperties.AdditionalBrowserArguments = "--disable-gpu --disable-gpu-compositing";
                web.CreationProperties.UserDataFolder = udf;

                web.Source = new Uri(url);
            }
            catch (Exception ex)
            {
                MessageBox.Show("窗口初始化失败：" + ex.Message, "大肥鱼监测");
                return;
            }

            form.Controls.Add(web);

            // 记下自己的进程号，下次启动靠它找到这个窗口
            try
            {
                Directory.CreateDirectory(dataDir);
                File.WriteAllText(PidFile(dataDir), System.Diagnostics.Process.GetCurrentProcess().Id.ToString());
            }
            catch (Exception) { }

            // ---- 托盘：关窗口不退出，缩到托盘继续监控 ----
            bool exiting = false;
            string trayState = Path.Combine(dataDir, "tray.txt");

            NotifyIcon tray = new NotifyIcon();
            tray.Icon = form.Icon != null ? form.Icon : SystemIcons.Application;
            tray.Text = "大肥鱼监测";
            tray.Visible = true;

            ContextMenuStrip menu = new ContextMenuStrip();
            menu.Items.Add("显示窗口", null, delegate
            {
                form.Show();
                form.WindowState = FormWindowState.Normal;
                form.Activate();
                try { File.WriteAllText(trayState, "shown"); } catch (Exception) { }
            });
            menu.Items.Add("打开数据目录", null, delegate
            {
                try { System.Diagnostics.Process.Start("explorer.exe", dataDir); } catch (Exception) { }
            });
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("退出", null, delegate
            {
                exiting = true;
                form.Close();
            });
            tray.ContextMenuStrip = menu;
            tray.DoubleClick += delegate
            {
                form.Show();
                form.WindowState = FormWindowState.Normal;
                form.Activate();
                try { File.WriteAllText(trayState, "shown"); } catch (Exception) { }
            };

            form.FormClosing += delegate(object sender, FormClosingEventArgs e)
            {
                try
                {
                    string folder = Path.GetDirectoryName(statePath);
                    if (!Directory.Exists(folder)) Directory.CreateDirectory(folder);
                    File.WriteAllText(statePath, form.Left + "," + form.Top + "," + form.Width + "," + form.Height);
                }
                catch (Exception) { }

                if (!trayMode)
                {
                    // 默认：关窗即退出，避免进程留在后台又找不到托盘图标
                    exiting = true;
                    try { File.WriteAllText(trayState, "closed"); } catch (Exception) { }
                    tray.Visible = false;
                    tray.Dispose();
                    return;
                }

                if (!exiting)
                {
                    e.Cancel = true;
                    form.Hide();
                    try
                    {
                        File.WriteAllText(trayState, "hidden");
                        tray.ShowBalloonTip(1500, "大肥鱼监测", "仍在后台运行，双击托盘图标可以再打开。", ToolTipIcon.Info);
                    }
                    catch (Exception) { }
                }
                else
                {
                    try { File.WriteAllText(trayState, "closed"); } catch (Exception) { }
                    tray.Visible = false;
                    tray.Dispose();
                }
            };

            // 首帧重绘：个别机器上 WebView2 初始化后不刷新，窗口一片黑。
            // 轻微改变客户区尺寸可以强制合成器重绘，这里在显示后连做两次兜底。
            Action repaint = delegate
            {
                try
                {
                    int w = form.Width;
                    form.Width = w + 1;
                    form.Width = w;
                    web.Invalidate(true);
                }
                catch (Exception) { }
            };
            form.Shown += delegate
            {
                // 显式激活，避免窗口虽显示但未成为前台，WebView2 不出帧
                try { form.Activate(); form.BringToFront(); } catch (Exception) { }
                // 后台等窗口合成完成，再回主线程轻推尺寸，强制 WebView2 出首帧
                System.Threading.Tasks.Task.Run(delegate
                {
                    int[] delays = new int[] { 600, 1500, 3000 };
                    foreach (int d in delays)
                    {
                        try { System.Threading.Thread.Sleep(d); } catch (Exception) { }
                        try { form.BeginInvoke(new Action(repaint)); } catch (Exception) { }
                    }
                });
            };
            Application.Run(form);        }
    }
}
