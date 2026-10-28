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

        private const int SW_RESTORE = 9;
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
            form.Text = "子漾监测";
            form.BackColor = Color.FromArgb(19, 21, 25);
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
                web.CreationProperties.UserDataFolder = udf;
                web.Source = new Uri(url);
            }
            catch (Exception ex)
            {
                MessageBox.Show("窗口初始化失败：" + ex.Message, "子漾监测");
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
            tray.Text = "子漾监测";
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

                if (!exiting)
                {
                    e.Cancel = true;
                    form.Hide();
                    try
                    {
                        File.WriteAllText(trayState, "hidden");
                        tray.ShowBalloonTip(1500, "子漾监测", "仍在后台运行，双击托盘图标可以再打开。", ToolTipIcon.Info);
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

            Application.Run(form);        }
    }
}
