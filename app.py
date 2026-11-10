"""Monitor PC - versão básica de teste.
Abas: Resumo, Processos, Disco, Temperaturas, Drivers.
"""
import json
import os
import subprocess
import threading
import tkinter as tk
from collections import defaultdict
from tkinter import filedialog, ttk

import psutil

import abas_extra
import historico

try:
    import tray
except Exception:  # sem pystray/pillow: roda sem bandeja
    tray = None

NOFLAG = 0x08000000  # CREATE_NO_WINDOW


def ps(cmd, timeout=120):
    """Roda um comando PowerShell e devolve o texto."""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True, text=True, timeout=timeout, creationflags=NOFLAG,
    )
    return r.stdout.strip()


def gb(n):
    return f"{n / 1024**3:.1f} GB"


def mb(n):
    return f"{n / 1024**2:.0f} MB"


def make_tree(parent, cols, widths):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=cols, show="headings")
    for c, w in zip(cols, widths):
        tree.heading(c, text=c)
        tree.column(c, width=w, anchor="w")
    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return frame, tree


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Monitor PC")
        self.geometry("820x560")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.nb = nb

        self.build_resumo(nb)
        self.build_processos(nb)
        self.aba_hist = abas_extra.AbaHistorico(nb)
        nb.add(self.aba_hist, text="Histórico")
        self.build_disco(nb)
        nb.add(abas_extra.AbaLimpeza(nb), text="Limpeza")
        self.build_temps(nb)
        self.build_drivers(nb)
        nb.add(abas_extra.AbaSistema(nb, self.reiniciar_admin), text="Sistema")
        nb.bind("<<NotebookTabChanged>>", self.on_tab)

        # coleta de histórico + bandeja
        self.icon = None
        self.avisou_bandeja = False
        if tray:
            try:
                self.icon = tray.criar(lambda: self.after(0, self.abrir), lambda: self.after(0, self.sair))
                self.icon.run_detached()
            except Exception:
                self.icon = None
        self.coletor = historico.Coletor(self.alerta)
        self.coletor.start()
        self.protocol("WM_DELETE_WINDOW", self.fechar)

        psutil.cpu_percent()  # primeira leitura
        self.tick()

    # ---------- Bandeja / ciclo de vida ----------
    def on_tab(self, _):
        if self.nb.select() == str(self.aba_hist):
            self.aba_hist.atualizar()

    def alerta(self, titulo, msg):
        if self.icon:
            self.icon.notify(msg, titulo)

    def abrir(self):
        self.deiconify()
        self.lift()

    def fechar(self):
        if self.icon:
            self.withdraw()
            if not self.avisou_bandeja:
                self.avisou_bandeja = True
                self.icon.notify("Continua coletando o histórico. Use o ícone para abrir ou sair.", "Monitor PC")
        else:
            self.sair()

    def sair(self):
        self.coletor.parar()
        if self.icon:
            self.icon.stop()
        self.destroy()

    def reiniciar_admin(self):
        abas_extra.relancar_como_admin()
        self.sair()

    # ---------- Resumo ----------
    def build_resumo(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Resumo")
        self.bars = {}
        for name in ("CPU", "RAM"):
            ttk.Label(f, text=name).pack(anchor="w")
            pb = ttk.Progressbar(f, maximum=100, length=500)
            pb.pack(anchor="w", pady=(0, 2))
            lb = ttk.Label(f, text="")
            lb.pack(anchor="w", pady=(0, 10))
            self.bars[name] = (pb, lb)
        ttk.Label(f, text="Discos").pack(anchor="w")
        self.disk_box = ttk.Frame(f)
        self.disk_box.pack(anchor="w", fill="x")
        self.alert_lbl = ttk.Label(f, text="", foreground="#b00020", justify="left")
        self.alert_lbl.pack(anchor="w", pady=15)

    def update_resumo(self):
        cpu = psutil.cpu_percent()
        vm = psutil.virtual_memory()
        pb, lb = self.bars["CPU"]
        pb["value"] = cpu
        lb["text"] = f"{cpu:.0f}%"
        pb, lb = self.bars["RAM"]
        pb["value"] = vm.percent
        lb["text"] = f"{vm.percent:.0f}%  ({gb(vm.used)} de {gb(vm.total)})"

        for w in self.disk_box.winfo_children():
            w.destroy()
        alerts = []
        for p in psutil.disk_partitions():
            if "cdrom" in p.opts or not p.fstype:
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
            except OSError:
                continue
            row = ttk.Frame(self.disk_box)
            row.pack(anchor="w", pady=2)
            ttk.Label(row, text=f"{p.device}", width=6).pack(side="left")
            pbar = ttk.Progressbar(row, maximum=100, length=300, value=u.percent)
            pbar.pack(side="left")
            ttk.Label(row, text=f"  {u.percent:.0f}% usado - livre {gb(u.free)} de {gb(u.total)}").pack(side="left")
            if u.percent > 90:
                alerts.append(f"⚠ {p.device} com pouco espaço livre ({gb(u.free)}).")
        if vm.percent > 85:
            alerts.append("⚠ RAM acima de 85%. Feche programas pesados.")
        if cpu > 90:
            alerts.append("⚠ CPU acima de 90%.")
        self.alert_lbl["text"] = "\n".join(alerts)

    # ---------- Processos ----------
    def build_processos(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Processos")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="Agrupado por programa (soma de todos os processos). Atualiza a cada 3s.").pack(side="left")
        ttk.Button(top, text="Encerrar selecionado", command=self.kill_selected).pack(side="right")
        frame, self.proc_tree = make_tree(f, ("Programa", "RAM", "CPU %", "Processos"), (280, 110, 90, 90))
        frame.pack(fill="both", expand=True, pady=6)
        self.proc_ticks = 0

    def update_procs(self):
        groups = defaultdict(lambda: [0, 0.0, 0])
        for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
            try:
                g = groups[p.info["name"] or "?"]
                g[0] += p.info["memory_info"].rss
                g[1] += p.info["cpu_percent"] or 0
                g[2] += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
        rows = sorted(groups.items(), key=lambda kv: kv[1][0], reverse=True)[:40]
        sel = self.proc_tree.selection()
        keep = self.proc_tree.item(sel[0])["values"][0] if sel else None
        self.proc_tree.delete(*self.proc_tree.get_children())
        for name, (mem, cpu, n) in rows:
            iid = self.proc_tree.insert("", "end", values=(name, mb(mem), f"{cpu / psutil.cpu_count():.1f}", n))
            if name == keep:
                self.proc_tree.selection_set(iid)

    def kill_selected(self):
        sel = self.proc_tree.selection()
        if not sel:
            return
        name = self.proc_tree.item(sel[0])["values"][0]
        from tkinter import messagebox
        if not messagebox.askyesno("Confirmar", f"Encerrar TODOS os processos '{name}'?"):
            return
        for p in psutil.process_iter(["name"]):
            if p.info["name"] == name:
                try:
                    p.terminate()
                except Exception:
                    pass

    # ---------- Disco ----------
    def build_disco(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Disco")
        top = ttk.Frame(f)
        top.pack(fill="x")
        self.scan_path = tk.StringVar(value=os.path.expanduser("~"))
        ttk.Entry(top, textvariable=self.scan_path, width=50).pack(side="left")
        ttk.Button(top, text="Escolher...", command=lambda: self.scan_path.set(
            filedialog.askdirectory() or self.scan_path.get())).pack(side="left", padx=4)
        self.scan_btn = ttk.Button(top, text="Analisar", command=self.start_scan)
        self.scan_btn.pack(side="left")
        self.scan_lbl = ttk.Label(f, text="Mostra as maiores subpastas (só lê, não apaga nada).")
        self.scan_lbl.pack(anchor="w", pady=4)
        frame, self.disk_tree = make_tree(f, ("Pasta", "Tamanho"), (600, 120))
        frame.pack(fill="both", expand=True)
        self.disk_tree.bind("<Double-1>", self.open_folder)

    def open_folder(self, _):
        sel = self.disk_tree.selection()
        if sel:
            os.startfile(self.disk_tree.item(sel[0])["values"][0])

    def start_scan(self):
        self.scan_btn.state(["disabled"])
        self.scan_lbl["text"] = "Analisando... pode levar alguns minutos."
        self.disk_tree.delete(*self.disk_tree.get_children())
        threading.Thread(target=self.scan, args=(self.scan_path.get(),), daemon=True).start()

    @staticmethod
    def folder_size(path):
        total = 0
        stack = [path]
        while stack:
            try:
                with os.scandir(stack.pop()) as it:
                    for e in it:
                        try:
                            if e.is_symlink():
                                continue
                            if e.is_dir(follow_symlinks=False):
                                stack.append(e.path)
                            else:
                                total += e.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
            except OSError:
                pass
        return total

    def scan(self, root):
        res = []
        try:
            with os.scandir(root) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            res.append((e.path, self.folder_size(e.path)))
                        else:
                            res.append((e.path, e.stat().st_size))
                    except OSError:
                        pass
        except OSError:
            pass
        res.sort(key=lambda x: x[1], reverse=True)
        self.after(0, self.show_scan, res[:60])

    def show_scan(self, res):
        for p, s in res:
            self.disk_tree.insert("", "end", values=(p, gb(s) if s > 1024**3 else mb(s)))
        self.scan_lbl["text"] = "Pronto. Clique duas vezes numa linha para abrir a pasta."
        self.scan_btn.state(["!disabled"])

    # ---------- Temperaturas ----------
    def build_temps(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Temperaturas")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Button(top, text="Ler agora", command=self.read_temps).pack(side="left")
        self.temp_lbl = ttk.Label(top, text="  Precisa da LibreHardwareMonitor aberta (como administrador).")
        self.temp_lbl.pack(side="left")
        frame, self.temp_tree = make_tree(f, ("Sensor", "Tipo", "Valor"), (360, 120, 120))
        frame.pack(fill="both", expand=True, pady=6)

    def read_temps(self):
        self.temp_tree.delete(*self.temp_tree.get_children())
        self.temp_lbl["text"] = "  Lendo..."
        threading.Thread(target=self._temps_worker, daemon=True).start()

    def _temps_worker(self):
        cmd = ("Get-CimInstance -Namespace root\\LibreHardwareMonitor -ClassName Sensor "
               "-ErrorAction Stop | Where-Object { $_.SensorType -in 'Temperature','Fan','Load' } "
               "| Select-Object Name,SensorType,Value | ConvertTo-Json")
        try:
            out = ps(cmd, 30)
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            self.after(0, self.show_temps, data, None)
        except Exception as e:
            self.after(0, self.show_temps, [], str(e))

    def show_temps(self, data, err):
        if not data:
            self.temp_lbl["text"] = ("  Sem dados. Baixe e abra a LibreHardwareMonitor como administrador "
                                     "(librehardwaremonitor.org).")
            return
        units = {"Temperature": "°C", "Fan": " RPM", "Load": " %"}
        for d in data:
            self.temp_tree.insert("", "end", values=(d["Name"], d["SensorType"],
                                                    f"{d['Value']:.0f}{units.get(d['SensorType'], '')}"))
        self.temp_lbl["text"] = f"  {len(data)} sensores."

    # ---------- Drivers ----------
    def build_drivers(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Drivers")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Button(top, text="Listar drivers", command=self.list_drivers).pack(side="left")
        ttk.Button(top, text="Abrir Windows Update", command=lambda: os.startfile("ms-settings:windowsupdate")).pack(side="left", padx=4)
        self.drv_lbl = ttk.Label(top, text="  Mostra os mais antigos primeiro.")
        self.drv_lbl.pack(side="left")
        frame, self.drv_tree = make_tree(f, ("Dispositivo", "Fabricante", "Versão", "Data"), (300, 200, 130, 100))
        frame.pack(fill="both", expand=True, pady=6)

    def list_drivers(self):
        self.drv_tree.delete(*self.drv_tree.get_children())
        self.drv_lbl["text"] = "  Lendo..."
        threading.Thread(target=self._drivers_worker, daemon=True).start()

    def _drivers_worker(self):
        cmd = ("Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceName -and $_.DriverDate } "
               "| Sort-Object DriverDate | Select-Object -First 150 DeviceName,Manufacturer,DriverVersion,"
               "@{n='Date';e={$_.DriverDate.ToString('yyyy-MM-dd')}} | ConvertTo-Json")
        try:
            data = json.loads(ps(cmd) or "[]")
        except Exception:
            data = []
        self.after(0, self.show_drivers, data)

    def show_drivers(self, data):
        for d in data:
            self.drv_tree.insert("", "end", values=(d["DeviceName"], d["Manufacturer"], d["DriverVersion"], d["Date"]))
        self.drv_lbl["text"] = f"  {len(data)} drivers (mais antigos primeiro)."

    # ---------- Loop ----------
    def tick(self):
        if self.state() == "withdrawn":  # janela escondida na bandeja
            self.after(2000, self.tick)
            return
        self.update_resumo()
        self.proc_ticks += 1
        if self.proc_ticks % 3 == 1:
            self.update_procs()
        self.after(1000, self.tick)


if __name__ == "__main__":
    App().mainloop()
