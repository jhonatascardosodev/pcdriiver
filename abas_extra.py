"""Abas extras: Histórico (gráfico), Limpeza de disco e Sistema (pagefile)."""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import psutil

import historico

NOFLAG = 0x08000000


def ps(cmd, timeout=120):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=timeout, creationflags=NOFLAG)
    return r.returncode, (r.stdout + r.stderr).strip()


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def gb(n):
    return f"{n / 1024**3:.1f} GB"


def fmt(n):
    return gb(n) if n >= 1024**3 else f"{n / 1024**2:.0f} MB"


def tamanho_pasta(path):
    total = 0
    pilha = [path]
    while pilha:
        try:
            with os.scandir(pilha.pop()) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            pilha.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


# ======================= Histórico =======================
PERIODOS = {
    "Última 1 hora": 3600,
    "Últimas 6 horas": 6 * 3600,
    "Últimas 24 horas": 24 * 3600,
    "Últimos 7 dias": 7 * 86400,
}


class AbaHistorico(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=6)
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Período:").pack(side="left")
        self.periodo = ttk.Combobox(top, values=list(PERIODOS), state="readonly", width=18)
        self.periodo.current(0)
        self.periodo.pack(side="left", padx=4)
        self.periodo.bind("<<ComboboxSelected>>", lambda _: self.atualizar())
        ttk.Button(top, text="Atualizar", command=self.atualizar).pack(side="left")
        self.info = ttk.Label(top, text="")
        self.info.pack(side="left", padx=8)

        self.canvas = tk.Canvas(self, height=230, bg="white", highlightthickness=1,
                                highlightbackground="#bbb")
        self.canvas.pack(fill="x", pady=6)
        self.canvas.bind("<Configure>", lambda _: self.desenhar())

        ttk.Label(self, text="Maiores picos de RAM no período (quem estava consumindo):").pack(anchor="w")
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        cols = ("Hora", "RAM %", "CPU %", "Mais RAM", "Mais CPU")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=8)
        for c, w in zip(cols, (110, 60, 60, 300, 220)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.rows = []

    def atualizar(self):
        seg = PERIODOS[self.periodo.get()]
        try:
            self.rows = historico.consultar(seg)
        except Exception:
            self.rows = []
        self.desenhar()
        self.tree.delete(*self.tree.get_children())
        fmt_hora = "%H:%M:%S" if seg <= 86400 else "%d/%m %H:%M"
        for ts, cpu, ram, top in sorted(self.rows, key=lambda r: r[2], reverse=True)[:15]:
            try:
                d = json.loads(top)
            except Exception:
                d = {"ram": [], "cpu": []}
            mais_ram = ", ".join(f"{n} {m} MB" for n, m in d["ram"])
            mais_cpu = ", ".join(f"{n} {p}%" for n, p in d["cpu"])
            self.tree.insert("", "end", values=(time.strftime(fmt_hora, time.localtime(ts)),
                                                f"{ram:.0f}", f"{cpu:.0f}", mais_ram, mais_cpu))
        self.info["text"] = f"{len(self.rows)} amostras"

    def desenhar(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50:
            return
        ml, mr, mt, mb = 40, 10, 22, 22
        pw, ph = w - ml - mr, h - mt - mb
        for v in (0, 25, 50, 75, 100):
            y = mt + ph - ph * v / 100
            c.create_line(ml, y, w - mr, y, fill="#e5e5e5")
            c.create_text(ml - 6, y, text=f"{v}%", anchor="e", fill="#666", font=("Segoe UI", 8))
        c.create_text(ml, 8, text="■ CPU", anchor="w", fill="#1f77b4", font=("Segoe UI", 9, "bold"))
        c.create_text(ml + 60, 8, text="■ RAM", anchor="w", fill="#e67e22", font=("Segoe UI", 9, "bold"))
        if len(self.rows) < 2:
            c.create_text(w / 2, h / 2, fill="#888",
                          text="Sem dados ainda. Deixe o programa aberto (ou na bandeja) para coletar.")
            return
        t0, t1 = self.rows[0][0], self.rows[-1][0]
        span = max(t1 - t0, 1)
        passo = max(1, len(self.rows) // (pw * 2 or 1))
        pts = self.rows[::passo]
        for idx, cor in ((1, "#1f77b4"), (2, "#e67e22")):
            coords = []
            for r in pts:
                coords += [ml + pw * (r[0] - t0) / span, mt + ph - ph * min(r[idx], 100) / 100]
            if len(coords) >= 4:
                c.create_line(*coords, fill=cor, width=2)
        f = "%H:%M" if (t1 - t0) <= 86400 else "%d/%m %H:%M"
        c.create_text(ml, h - 8, text=time.strftime(f, time.localtime(t0)), anchor="w", fill="#666", font=("Segoe UI", 8))
        c.create_text(w - mr, h - 8, text=time.strftime(f, time.localtime(t1)), anchor="e", fill="#666", font=("Segoe UI", 8))


# ======================= Limpeza =======================
def _itens_limpeza():
    local = os.environ.get("LOCALAPPDATA", "")
    brave = os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "Default")
    return [
        ("Arquivos temporários do usuário", [os.environ.get("TEMP", "")], "pastas"),
        ("Arquivos temporários do Windows (precisa de administrador)", [r"C:\Windows\Temp"], "pastas"),
        ("Cache do Brave (feche o Brave antes)",
         [os.path.join(brave, "Cache"), os.path.join(brave, "Code Cache"), os.path.join(brave, "GPUCache")], "pastas"),
        ("Lixeira", [], "lixeira"),
        ("Cache do npm (baixa de novo quando precisar)", [os.path.join(local, "npm-cache")], "npm"),
        ("Cache de shaders da NVIDIA (o driver recria; jogos podem travar um pouco na 1ª vez)",
         [os.path.join(local, "NVIDIA", "DXCache"), os.path.join(local, "NVIDIA", "GLCache")], "pastas"),
    ]


def rodar_limpeza_cmd(tipo, paths):
    """pnpm/npm têm comando próprio de limpeza. Devolve bytes liberados."""
    exe = shutil.which("pnpm" if tipo == "pnpm" else "npm")
    if not exe:
        return 0
    args = [exe, "store", "prune"] if tipo == "pnpm" else [exe, "cache", "clean", "--force"]
    antes = sum(tamanho_pasta(p) for p in paths)
    try:
        subprocess.run(args, capture_output=True, timeout=600, creationflags=NOFLAG)
    except Exception:
        return 0
    return max(0, antes - sum(tamanho_pasta(p) for p in paths))


def esvaziar_pasta(path):
    """Apaga o conteúdo (não a pasta). Arquivos em uso são ignorados."""
    liberado = 0
    try:
        itens = list(os.scandir(path))
    except OSError:
        return 0
    for e in itens:
        try:
            if e.is_dir(follow_symlinks=False):
                antes = tamanho_pasta(e.path)
                shutil.rmtree(e.path, ignore_errors=True)
                depois = tamanho_pasta(e.path) if os.path.exists(e.path) else 0
                liberado += antes - depois
            else:
                s = e.stat(follow_symlinks=False).st_size
                os.remove(e.path)
                liberado += s
        except OSError:
            pass
    return liberado


class AbaLimpeza(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=10)
        ttk.Label(self, text="Selecione o que limpar. Nada é apagado até você confirmar.").pack(anchor="w")
        self.itens = _itens_limpeza()
        self.vars, self.labels = [], []
        box = ttk.Frame(self)
        box.pack(fill="x", pady=10)
        for i, (nome, _, _) in enumerate(self.itens):
            v = tk.BooleanVar(value=(i != 1))  # Windows\Temp desmarcado por padrão
            self.vars.append(v)
            ttk.Checkbutton(box, text=nome, variable=v).grid(row=i, column=0, sticky="w", pady=2)
            lb = ttk.Label(box, text="—", width=14, anchor="e")
            lb.grid(row=i, column=1, padx=10)
            self.labels.append(lb)
        btns = ttk.Frame(self)
        btns.pack(anchor="w")
        self.btn_calc = ttk.Button(btns, text="Calcular tamanhos", command=self.calcular)
        self.btn_calc.pack(side="left")
        self.btn_limpar = ttk.Button(btns, text="Limpar selecionados", command=self.limpar)
        self.btn_limpar.pack(side="left", padx=6)
        self.status = ttk.Label(self, text="", justify="left")
        self.status.pack(anchor="w", pady=10)

    def _tamanho_item(self, i):
        _, paths, tipo = self.itens[i]
        if tipo == "lixeira":
            _, out = ps("$s=(New-Object -ComObject Shell.Application).NameSpace(0xA); "
                        "($s.Items() | ForEach-Object { $_.Size } | Measure-Object -Sum).Sum")
            try:
                return int(float(out.split()[-1]))
            except (ValueError, IndexError):
                return 0
        return sum(tamanho_pasta(p) for p in paths if p)

    def calcular(self):
        self.btn_calc.state(["disabled"])
        self.status["text"] = "Calculando..."
        threading.Thread(target=self._calcular_worker, daemon=True).start()

    def _calcular_worker(self):
        tam = [self._tamanho_item(i) for i in range(len(self.itens))]
        self.after(0, self._mostrar, tam)

    def _mostrar(self, tam):
        for lb, t in zip(self.labels, tam):
            lb["text"] = fmt(t)
        self.tamanhos = tam
        self.status["text"] = f"Total possível: {fmt(sum(tam))}"
        self.btn_calc.state(["!disabled"])

    def limpar(self):
        sel = [i for i, v in enumerate(self.vars) if v.get()]
        if not sel:
            return
        nomes = "\n".join("• " + self.itens[i][0] for i in sel)
        if not messagebox.askyesno("Confirmar limpeza", f"Vai apagar o conteúdo de:\n\n{nomes}\n\nContinuar?"):
            return
        self.btn_limpar.state(["disabled"])
        self.status["text"] = "Limpando..."
        threading.Thread(target=self._limpar_worker, args=(sel,), daemon=True).start()

    def _limpar_worker(self, sel):
        total = 0
        for i in sel:
            _, paths, tipo = self.itens[i]
            if tipo == "lixeira":
                antes = self._tamanho_item(i)
                ps("Clear-RecycleBin -Force -ErrorAction SilentlyContinue")
                total += antes
            elif tipo in ("pnpm", "npm"):
                total += rodar_limpeza_cmd(tipo, paths)
            else:
                total += sum(esvaziar_pasta(p) for p in paths if p)
        self.after(0, self._fim_limpeza, total)

    def _fim_limpeza(self, total):
        self.btn_limpar.state(["!disabled"])
        self.status["text"] = f"Liberado: {fmt(total)}. (Arquivos em uso foram ignorados.)"
        self.calcular()


# ======================= Sistema (pagefile) =======================
class AbaSistema(ttk.Frame):
    def __init__(self, master, reiniciar_admin):
        super().__init__(master, padding=10)
        self.reiniciar_admin = reiniciar_admin
        self.txt = tk.Label(self, text="", justify="left", anchor="w", font=("Segoe UI", 10))
        self.txt.pack(anchor="w", fill="x")
        btns = ttk.Frame(self)
        btns.pack(anchor="w", pady=12)
        ttk.Button(btns, text="Atualizar", command=self.atualizar).pack(side="left")
        ttk.Button(btns, text="Mover pagefile para o SSD (C:)", command=self.mover).pack(side="left", padx=6)
        if not is_admin():
            ttk.Button(btns, text="Reiniciar como administrador", command=self.reiniciar_admin).pack(side="left")
        self.nota = ttk.Label(self, wraplength=700, justify="left", foreground="#555",
                              text=("O pagefile é a 'memória de reserva' usada quando a RAM aperta. Em HDD ele deixa "
                                    "o PC lento. Mudar exige administrador e reiniciar o PC. "
                                    "Libere espaço no C: antes (a aba Limpeza ajuda)."))
        self.nota.pack(anchor="w", pady=8)
        self.atualizar()

    def atualizar(self):
        linhas = [f"Administrador: {'sim' if is_admin() else 'não'}"]
        try:
            livre = psutil.disk_usage("C:\\").free
            linhas.append(f"Espaço livre no C: {gb(livre)}")
        except OSError:
            pass
        _, out = ps("Get-CimInstance Win32_PageFileUsage | ForEach-Object { $_.Name + '|' + $_.AllocatedBaseSize + '|' + $_.CurrentUsage }")
        pf = [l for l in out.splitlines() if "|" in l]
        if not pf:
            linhas.append("Pagefile: nenhum encontrado")
        for l in pf:
            nome, tam, uso = l.split("|")[:3]
            onde = "SSD (sistema)" if nome.upper().startswith("C:") else "OUTRO DISCO (pode ser lento)"
            linhas.append(f"Pagefile: {nome} — {tam} MB alocados, {uso} MB em uso — {onde}")
        self.txt["text"] = "\n".join(linhas)

    def mover(self):
        if not is_admin():
            messagebox.showwarning("Precisa de administrador",
                                   "Clique em 'Reiniciar como administrador' e tente de novo.")
            return
        livre = psutil.disk_usage("C:\\").free
        aviso = ""
        if livre < 12 * 1024**3:
            aviso = f"\n\nATENÇÃO: o C: tem só {gb(livre)} livres. Limpe espaço antes."
        if not messagebox.askyesno(
                "Confirmar",
                "Isto vai:\n• desligar o pagefile automático\n• remover o pagefile dos outros discos\n"
                "• criar pagefile no C: (2 GB a 6 GB)\n\nPrecisa reiniciar o PC depois."
                + aviso + "\n\nContinuar?"):
            return
        cmd = ("$ErrorActionPreference='Stop'; "
               "$cs=Get-CimInstance Win32_ComputerSystem; "
               "Set-CimInstance -InputObject $cs -Property @{AutomaticManagedPagefile=$false}; "
               "Get-CimInstance Win32_PageFileSetting -ErrorAction SilentlyContinue | Remove-CimInstance; "
               "New-CimInstance -ClassName Win32_PageFileSetting -Property "
               "@{Name='C:\\pagefile.sys'; InitialSize=[uint32]2048; MaximumSize=[uint32]6144} | Out-Null; "
               "'OK'")
        rc, out = ps(cmd)
        if rc == 0 and out.endswith("OK"):
            messagebox.showinfo("Pronto", "Configurado. Reinicie o PC para aplicar.")
        else:
            messagebox.showerror("Erro", out[:600] or "Falhou.")
        self.atualizar()


def relancar_como_admin():
    """Reabre este programa pedindo permissão de administrador."""
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, f'"{script}"',
                                        os.path.dirname(script), 1)
