"""Abas extras: Histórico (gráfico interativo), Limpeza de disco e Sistema (pagefile)."""
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
import ui

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


def titulo(parent, texto, sub=None):
    f = ttk.Frame(parent)
    ttk.Label(f, text=texto, font=(ui.FONTE, 13, "bold")).pack(anchor="w")
    if sub:
        ttk.Label(f, text=sub, foreground=ui.Tema.p()["mut"], wraplength=760,
                  justify="left").pack(anchor="w")
    return f


# ======================= Histórico =======================
PERIODOS = {
    "Última 1 hora": 3600,
    "Últimas 6 horas": 6 * 3600,
    "Últimas 24 horas": 24 * 3600,
    "Últimos 7 dias": 7 * 86400,
}


class AbaHistorico(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=12)
        titulo(self, "Histórico", "Passe o mouse sobre o gráfico para ver o que estava consumindo naquele instante.").pack(anchor="w")
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(8, 6))
        ttk.Label(top, text="Período:").pack(side="left")
        self.periodo = ttk.Combobox(top, values=list(PERIODOS), state="readonly", width=18)
        self.periodo.current(0)
        self.periodo.pack(side="left", padx=6)
        self.periodo.bind("<<ComboboxSelected>>", lambda _: self.atualizar())
        ttk.Button(top, text="Atualizar", command=self.atualizar).pack(side="left")
        self.info = ttk.Label(top, text="", foreground=ui.Tema.p()["mut"])
        self.info.pack(side="left", padx=10)

        card = ui.Cartao(self)
        card.pack(fill="x", pady=4)
        self.grafico = ui.Grafico(card, [(1, "CPU", "cpu"), (2, "RAM", "ram")], altura=240, dica=self.dica)
        self.grafico.pack(fill="x", padx=8, pady=8)

        ttk.Label(self, text="Maiores picos de RAM no período (quem estava consumindo)",
                  font=(ui.FONTE, 10, "bold")).pack(anchor="w", pady=(10, 4))
        frame, self.tree = ui.criar_tree(
            self, ("Hora", "RAM %", "CPU %", "Mais RAM", "Mais CPU"), (110, 70, 70, 330, 240), altura=7)
        frame.pack(fill="both", expand=True)
        self.rows = []

    @staticmethod
    def _top(row):
        try:
            return json.loads(row[3])
        except Exception:
            return {"ram": [], "cpu": []}

    def dica(self, row):
        d = row[3] if isinstance(row[3], dict) else {"ram": [], "cpu": []}
        linhas = [time.strftime("%d/%m %H:%M:%S", time.localtime(row[0])),
                  f"CPU {row[1]:.0f}%   RAM {row[2]:.0f}%"]
        if d["ram"]:
            linhas.append("Mais RAM: " + ", ".join(f"{n} {m} MB" for n, m in d["ram"][:3]))
        if d["cpu"]:
            linhas.append("Mais CPU: " + ", ".join(f"{n} {p}%" for n, p in d["cpu"][:3]))
        return linhas

    def atualizar(self):
        seg = PERIODOS[self.periodo.get()]
        try:
            self.rows = historico.consultar(seg)
        except Exception:
            self.rows = []
        self.grafico.set_rows([(ts, cpu, ram, self._top((ts, cpu, ram, top)))
                               for ts, cpu, ram, top in self.rows])
        self.tree.delete(*self.tree.get_children())
        fmt_hora = "%H:%M:%S" if seg <= 86400 else "%d/%m %H:%M"
        for ts, cpu, ram, top in sorted(self.rows, key=lambda r: r[2], reverse=True)[:15]:
            d = self._top((ts, cpu, ram, top))
            self.tree.insert("", "end", tags=("heavy",) if ram >= 90 else (),
                             values=(time.strftime(fmt_hora, time.localtime(ts)), f"{ram:.0f}", f"{cpu:.0f}",
                                     ", ".join(f"{n} {m} MB" for n, m in d["ram"]),
                                     ", ".join(f"{n} {p}%" for n, p in d["cpu"])))
        ui.reordenar(self.tree)
        self.info["text"] = f"{len(self.rows)} amostras"


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
    """npm/pnpm têm comando próprio de limpeza. Devolve bytes liberados."""
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
        super().__init__(master, padding=12)
        titulo(self, "Limpeza de disco",
               "Marque o que limpar. Nada é apagado até você confirmar; arquivos em uso são ignorados.").pack(anchor="w")
        self.itens = _itens_limpeza()
        self.vars, self.labels, self.barras = [], [], []
        box = ttk.Frame(self)
        box.pack(fill="x", pady=10)
        box.columnconfigure(0, weight=1)
        for i, (nome, _, _) in enumerate(self.itens):
            v = tk.BooleanVar(value=(i != 1))  # Windows\Temp desmarcado por padrão
            self.vars.append(v)
            ttk.Checkbutton(box, text=nome, variable=v).grid(row=i, column=0, sticky="w", pady=5)
            br = ui.Barra(box, aviso=40, perigo=80, largura=140, fundo="bg")
            br.grid(row=i, column=1, padx=10)
            self.barras.append(br)
            lb = ui.Texto(box, "—", tam=10, negrito=True, fundo="bg")
            lb.configure(width=10, anchor="e")
            lb.grid(row=i, column=2)
            self.labels.append(lb)
        btns = ttk.Frame(self)
        btns.pack(anchor="w")
        self.btn_calc = ttk.Button(btns, text="Calcular tamanhos", command=self.calcular)
        self.btn_calc.pack(side="left")
        self.btn_limpar = ttk.Button(btns, text="Limpar selecionados", style="Accent.TButton", command=self.limpar)
        self.btn_limpar.pack(side="left", padx=8)
        self.prog = ttk.Progressbar(btns, mode="indeterminate", length=160)
        self.status = ttk.Label(self, text="", font=(ui.FONTE, 11, "bold"))
        self.status.pack(anchor="w", pady=12)
        self.tamanhos = [0] * len(self.itens)

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

    def _ocupado(self, sim, texto=""):
        if sim:
            self.prog.pack(side="left", padx=8)
            self.prog.start(12)
            self.btn_calc.state(["disabled"])
            self.btn_limpar.state(["disabled"])
        else:
            self.prog.stop()
            self.prog.pack_forget()
            self.btn_calc.state(["!disabled"])
            self.btn_limpar.state(["!disabled"])
        self.status["text"] = texto

    def calcular(self):
        self._ocupado(True, "Calculando...")
        threading.Thread(target=self._calcular_worker, daemon=True).start()

    def _calcular_worker(self):
        tam = [self._tamanho_item(i) for i in range(len(self.itens))]
        self.after(0, self._mostrar, tam)

    def _mostrar(self, tam):
        self.tamanhos = tam
        maior = max(tam) or 1
        for lb, br, t in zip(self.labels, self.barras, tam):
            lb["text"] = fmt(t)
            br.set(100 * t / maior)
        self._ocupado(False, f"Total possível: {fmt(sum(tam))}")

    def limpar(self):
        sel = [i for i, v in enumerate(self.vars) if v.get()]
        if not sel:
            return
        nomes = "\n".join("• " + self.itens[i][0] for i in sel)
        if not messagebox.askyesno("Confirmar limpeza", f"Vai apagar o conteúdo de:\n\n{nomes}\n\nContinuar?"):
            return
        self._ocupado(True, "Limpando...")
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
        self._ocupado(False, f"Liberado: {fmt(total)}. (Arquivos em uso foram ignorados.)")
        self.calcular()


# ======================= Sistema (pagefile) =======================
class AbaSistema(ttk.Frame):
    def __init__(self, master, reiniciar_admin):
        super().__init__(master, padding=12)
        self.reiniciar_admin = reiniciar_admin
        titulo(self, "Sistema", "Memória virtual (pagefile) e permissões.").pack(anchor="w")
        card = ui.Cartao(self)
        card.pack(fill="x", pady=10)
        self.txt = ui.Texto(card, "", tam=10)
        self.txt.configure(justify="left", anchor="w")
        self.txt.pack(anchor="w", fill="x", padx=14, pady=12)
        btns = ttk.Frame(self)
        btns.pack(anchor="w")
        ttk.Button(btns, text="Atualizar", command=self.atualizar).pack(side="left")
        ttk.Button(btns, text="Mover pagefile para o SSD (C:)", style="Accent.TButton",
                   command=self.mover).pack(side="left", padx=8)
        if not is_admin():
            ttk.Button(btns, text="Reiniciar como administrador", command=self.reiniciar_admin).pack(side="left")
        ttk.Label(self, wraplength=760, justify="left", foreground=ui.Tema.p()["mut"],
                  text=("O pagefile é a 'memória de reserva' usada quando a RAM aperta. Em HDD ele deixa "
                        "o PC lento. Mudar exige administrador e reiniciar o PC. "
                        "Libere espaço no C: antes (a aba Limpeza ajuda).")).pack(anchor="w", pady=12)
        self.atualizar()

    def atualizar(self):
        linhas = [f"Administrador: {'sim' if is_admin() else 'não'}"]
        try:
            linhas.append(f"Espaço livre no C: {gb(psutil.disk_usage('C:' + chr(92)).free)}")
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
        livre = psutil.disk_usage("C:" + chr(92)).free
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
