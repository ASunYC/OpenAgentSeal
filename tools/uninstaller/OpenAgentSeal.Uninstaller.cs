using Microsoft.Win32;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Windows.Forms;

namespace OpenAgentSeal.Uninstaller
{
    internal static class Program
    {
        private const string ProductName = "OpenAgentSeal";
        private const string AppIdentifier = "com.openagentseal.desktop";
        private const string LogFileName = "OpenAgentSeal-Uninstaller.log";

        [STAThread]
        private static int Main(string[] args)
        {
            bool silent = HasArg(args, "/silent") || HasArg(args, "--silent") || HasArg(args, "/S");
            bool cleanData = HasArg(args, "/clean-data") || HasArg(args, "--clean-data");
            bool help = HasArg(args, "/help") || HasArg(args, "--help") || HasArg(args, "/?");

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            if (help)
            {
                ShowMessage(
                    "OpenAgentSeal Uninstaller\n\n" +
                    "Double click: uninstall OpenAgentSeal and keep user data.\n" +
                    "/silent: run without confirmation prompts when possible.\n" +
                    "/clean-data: also remove user data under the current Windows account.",
                    false,
                    MessageBoxIcon.Information);
                return 0;
            }

            try
            {
                if (!silent && !Confirm(cleanData))
                {
                    return 1;
                }

                StopRunningProcesses();

                UninstallEntry entry = FindUninstallEntry();
                if (entry == null)
                {
                    ShowMessage("OpenAgentSeal is not installed, or its uninstall entry was not found.", silent, MessageBoxIcon.Information);
                    return 2;
                }

                string uninstallCommand = silent && !string.IsNullOrWhiteSpace(entry.QuietUninstallString)
                    ? entry.QuietUninstallString
                    : entry.UninstallString;

                if (string.IsNullOrWhiteSpace(uninstallCommand))
                {
                    ShowMessage("OpenAgentSeal was found, but no uninstall command is available.", silent, MessageBoxIcon.Error);
                    return 3;
                }

                int exitCode = RunUninstallCommand(uninstallCommand, silent, entry.RequiresElevation);
                if (exitCode != 0 && exitCode != 3010)
                {
                    ShowMessage("The official uninstaller returned exit code " + exitCode + ".", silent, MessageBoxIcon.Warning);
                    return exitCode;
                }

                if (cleanData)
                {
                    RemoveUserData();
                }

                ShowMessage(
                    cleanData
                        ? "OpenAgentSeal has been uninstalled and current-user data has been removed."
                        : "OpenAgentSeal has been uninstalled. Current-user data was kept.",
                    silent,
                    MessageBoxIcon.Information);

                return exitCode;
            }
            catch (System.ComponentModel.Win32Exception ex) when (ex.NativeErrorCode == 1223)
            {
                ShowMessage("Uninstall was cancelled.", silent, MessageBoxIcon.Information);
                return 1223;
            }
            catch (Exception ex)
            {
                WriteLog(ex.ToString());
                ShowMessage("Uninstall failed: " + ex.Message, silent, MessageBoxIcon.Error);
                return 10;
            }
        }

        private static bool Confirm(bool cleanData)
        {
            string message = cleanData
                ? "This will uninstall OpenAgentSeal and remove current-user data. This cannot be undone. Continue?"
                : "This will uninstall OpenAgentSeal. Current-user data in .open-agent will be kept. Continue?";

            DialogResult result = MessageBox.Show(
                message,
                ProductName + " Uninstaller",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Warning,
                MessageBoxDefaultButton.Button2);

            return result == DialogResult.Yes;
        }

        private static bool HasArg(IEnumerable<string> args, string value)
        {
            return args.Any(arg => string.Equals(arg, value, StringComparison.OrdinalIgnoreCase));
        }

        private static void StopRunningProcesses()
        {
            string[] processNames =
            {
                "OpenAgentSeal",
                "open-agent-seal-desktop",
                "open-agent-backend-x86_64-pc-windows-msvc"
            };

            int currentPid = Process.GetCurrentProcess().Id;
            foreach (string processName in processNames)
            {
                foreach (Process process in Process.GetProcessesByName(processName))
                {
                    try
                    {
                        if (process.Id == currentPid)
                        {
                            continue;
                        }

                        process.CloseMainWindow();
                        if (!process.WaitForExit(2500))
                        {
                            process.Kill();
                            process.WaitForExit(5000);
                        }
                    }
                    catch (Exception ex)
                    {
                        WriteLog("Failed to stop " + processName + ": " + ex.Message);
                    }
                }
            }
        }

        private static UninstallEntry FindUninstallEntry()
        {
            RegistryRoot[] roots =
            {
                new RegistryRoot(RegistryHive.CurrentUser, RegistryView.Registry64, false),
                new RegistryRoot(RegistryHive.CurrentUser, RegistryView.Registry32, false),
                new RegistryRoot(RegistryHive.LocalMachine, RegistryView.Registry64, true),
                new RegistryRoot(RegistryHive.LocalMachine, RegistryView.Registry32, true)
            };

            foreach (RegistryRoot root in roots)
            {
                UninstallEntry entry = FindInRoot(root);
                if (entry != null)
                {
                    return entry;
                }
            }

            return null;
        }

        private static UninstallEntry FindInRoot(RegistryRoot root)
        {
            try
            {
                using (RegistryKey baseKey = RegistryKey.OpenBaseKey(root.Hive, root.View))
                using (RegistryKey uninstallKey = baseKey.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall"))
                {
                    if (uninstallKey == null)
                    {
                        return null;
                    }

                    foreach (string subKeyName in uninstallKey.GetSubKeyNames())
                    {
                        using (RegistryKey appKey = uninstallKey.OpenSubKey(subKeyName))
                        {
                            if (appKey == null)
                            {
                                continue;
                            }

                            string displayName = Convert.ToString(appKey.GetValue("DisplayName", "")) ?? "";
                            string uninstallString = Convert.ToString(appKey.GetValue("UninstallString", "")) ?? "";
                            string quietUninstallString = Convert.ToString(appKey.GetValue("QuietUninstallString", "")) ?? "";
                            string installLocation = Convert.ToString(appKey.GetValue("InstallLocation", "")) ?? "";
                            string publisher = Convert.ToString(appKey.GetValue("Publisher", "")) ?? "";

                            if (!MatchesOpenAgentSeal(subKeyName, displayName, uninstallString, installLocation, publisher))
                            {
                                continue;
                            }

                            return new UninstallEntry
                            {
                                DisplayName = displayName,
                                UninstallString = uninstallString,
                                QuietUninstallString = quietUninstallString,
                                InstallLocation = installLocation,
                                RequiresElevation = root.RequiresElevation
                            };
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                WriteLog("Registry scan failed for " + root.Hive + " " + root.View + ": " + ex.Message);
            }

            return null;
        }

        private static bool MatchesOpenAgentSeal(string keyName, string displayName, string uninstallString, string installLocation, string publisher)
        {
            return Contains(displayName, ProductName)
                || Contains(keyName, ProductName)
                || Contains(keyName, AppIdentifier)
                || Contains(uninstallString, ProductName)
                || Contains(installLocation, ProductName)
                || (Contains(displayName, "Open Agent Seal") && Contains(publisher, "OpenAgentSeal"));
        }

        private static bool Contains(string value, string token)
        {
            return !string.IsNullOrEmpty(value) && value.IndexOf(token, StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static int RunUninstallCommand(string commandLine, bool silent, bool requiresElevation)
        {
            string[] argv = CommandLineToArgs(commandLine);
            if (argv.Length == 0 || string.IsNullOrWhiteSpace(argv[0]))
            {
                throw new InvalidOperationException("The uninstall command is empty.");
            }

            string fileName = argv[0];
            string arguments = JoinArguments(argv.Skip(1));

            if (silent)
            {
                arguments = AddSilentArgumentIfUseful(fileName, arguments);
            }

            string workingDirectory = GetSafeWorkingDirectory(fileName);
            ProcessStartInfo startInfo = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                UseShellExecute = true,
                WorkingDirectory = workingDirectory
            };

            if (requiresElevation && !IsAdministrator())
            {
                startInfo.Verb = "runas";
            }

            WriteLog("Running uninstall command: " + fileName + " " + arguments);
            using (Process process = Process.Start(startInfo))
            {
                if (process == null)
                {
                    throw new InvalidOperationException("Unable to start the official uninstaller.");
                }

                process.WaitForExit();
                return process.ExitCode;
            }
        }

        private static string AddSilentArgumentIfUseful(string fileName, string arguments)
        {
            string lowerFileName = Path.GetFileName(fileName).ToLowerInvariant();

            if (lowerFileName == "msiexec.exe" || lowerFileName == "msiexec")
            {
                if (arguments.IndexOf("/qn", StringComparison.OrdinalIgnoreCase) < 0 &&
                    arguments.IndexOf("/quiet", StringComparison.OrdinalIgnoreCase) < 0)
                {
                    return string.IsNullOrWhiteSpace(arguments) ? "/qn" : arguments + " /qn";
                }
                return arguments;
            }

            if (Path.GetExtension(fileName).Equals(".exe", StringComparison.OrdinalIgnoreCase) &&
                arguments.IndexOf("/S", StringComparison.OrdinalIgnoreCase) < 0 &&
                arguments.IndexOf("--silent", StringComparison.OrdinalIgnoreCase) < 0 &&
                arguments.IndexOf("/silent", StringComparison.OrdinalIgnoreCase) < 0)
            {
                return string.IsNullOrWhiteSpace(arguments) ? "/S" : arguments + " /S";
            }

            return arguments;
        }

        private static string GetSafeWorkingDirectory(string fileName)
        {
            try
            {
                string directory = Path.GetDirectoryName(fileName);
                if (!string.IsNullOrEmpty(directory) && Directory.Exists(directory))
                {
                    return directory;
                }
            }
            catch
            {
                // Use the current directory below.
            }

            return Environment.CurrentDirectory;
        }

        private static void RemoveUserData()
        {
            string userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);

            DeleteKnownDirectory(Path.Combine(userProfile, ".open-agent"));
            DeleteKnownDirectory(Path.Combine(localAppData, ProductName));
            DeleteKnownDirectory(Path.Combine(localAppData, AppIdentifier));
        }

        private static void DeleteKnownDirectory(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                return;
            }

            string fullPath = Path.GetFullPath(path.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
            if (!Directory.Exists(fullPath))
            {
                return;
            }

            WriteLog("Removing data directory: " + fullPath);
            Directory.Delete(fullPath, true);
        }

        private static bool IsAdministrator()
        {
            using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
            {
                WindowsPrincipal principal = new WindowsPrincipal(identity);
                return principal.IsInRole(WindowsBuiltInRole.Administrator);
            }
        }

        private static string[] CommandLineToArgs(string commandLine)
        {
            IntPtr argv = CommandLineToArgvW(commandLine, out int argc);
            if (argv == IntPtr.Zero || argc == 0)
            {
                return new[] { commandLine };
            }

            try
            {
                string[] args = new string[argc];
                for (int i = 0; i < argc; i++)
                {
                    IntPtr pointer = Marshal.ReadIntPtr(argv, i * IntPtr.Size);
                    args[i] = Marshal.PtrToStringUni(pointer) ?? "";
                }
                return args;
            }
            finally
            {
                LocalFree(argv);
            }
        }

        private static string JoinArguments(IEnumerable<string> args)
        {
            return string.Join(" ", args.Select(QuoteArgument));
        }

        private static string QuoteArgument(string arg)
        {
            if (string.IsNullOrEmpty(arg))
            {
                return "\"\"";
            }

            if (arg.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
            {
                return arg;
            }

            StringBuilder builder = new StringBuilder("\"");
            foreach (char c in arg)
            {
                if (c == '"')
                {
                    builder.Append("\\\"");
                }
                else
                {
                    builder.Append(c);
                }
            }
            builder.Append('"');
            return builder.ToString();
        }

        private static void ShowMessage(string message, bool silent, MessageBoxIcon icon)
        {
            WriteLog(message);
            if (!silent)
            {
                MessageBox.Show(message, ProductName + " Uninstaller", MessageBoxButtons.OK, icon);
            }
        }

        private static void WriteLog(string message)
        {
            try
            {
                string logPath = Path.Combine(Path.GetTempPath(), LogFileName);
                File.AppendAllText(logPath, DateTime.Now.ToString("s") + " " + message + Environment.NewLine, Encoding.UTF8);
            }
            catch
            {
                // Ignore logging failures.
            }
        }

        [DllImport("shell32.dll", SetLastError = true)]
        private static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)] string lpCmdLine, out int pNumArgs);

        [DllImport("kernel32.dll")]
        private static extern IntPtr LocalFree(IntPtr hMem);

        private sealed class RegistryRoot
        {
            public RegistryRoot(RegistryHive hive, RegistryView view, bool requiresElevation)
            {
                Hive = hive;
                View = view;
                RequiresElevation = requiresElevation;
            }

            public RegistryHive Hive { get; private set; }
            public RegistryView View { get; private set; }
            public bool RequiresElevation { get; private set; }
        }

        private sealed class UninstallEntry
        {
            public string DisplayName { get; set; }
            public string UninstallString { get; set; }
            public string QuietUninstallString { get; set; }
            public string InstallLocation { get; set; }
            public bool RequiresElevation { get; set; }
        }
    }
}
