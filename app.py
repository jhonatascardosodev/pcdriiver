"""Monitor PC - painel de desempenho, histórico, limpeza e diagnóstico para Windows."""
import json
import os
import socket
import subprocess
import threading
import time
import tkinter as tk
from collections import defaultdict, deque
from tkinter import filedialog, messagebox, ttk

import psutil

import abas_extra
import historico
import meupc
import ui

try:
    import tray
except Exception:  # sem pystray/pillow: roda sem bandeja
    tray = None

NOFLAG = 0x08000000  # CREATE_NO_WINDOW


def ps(cmd, timeout=120):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=timeout, creationflags=NOFLAG)
    return r.stdout.strip()


def gb(n):
    return f"{n / 1024**3:.1f} GB"


def mb(n):
    return f"{n / 1024**2:.0f} MB"


def duracao(seg):
    seg = int(seg)
    d, r = divmod(seg, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    return (f"{d}d " if d else "") + f"{h:02d}h {m:02d}min"


ARQ_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# blocos do Resumo que o usuário pode mostrar ou esconder
BLOCOS = [
    ("cpu", "Medidor de CPU"),
    ("ram", "Medidor de memória RAM"),
    ("disco_c", "Medidor do disco C:"),
    ("sistema", "Cartão Sistema (tempo ligado, processos)"),
    ("temps", "Temperaturas"),
    ("grafico", "Gráfico de CPU e RAM ao vivo"),
    ("discos", "Lista de discos"),
    ("avisos", "Avisos"),
]


def ler_config():
    try:
        with open(ARQ_CONFIG, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def salvar_config(cfg):
    try:
        with open(ARQ_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class CartaoTemp(tk.Frame):
    """Cartão de temperatura: nome, valor grande e barra colorida."""

    def __init__(self, parent, titulo, sub, aviso, perigo):
        super().__init__(parent, bd=0, highlightthickness=1)
        self._estilo = ("card", None)
        self._borda = True
        self.aviso, self.perigo = aviso, perigo
        p = ui.Tema.p()
        self.configure(bg=p["card"], highlightbackground=p["grid"])
        ui.Texto(self, titulo, 10, True).pack(anchor="w", padx=12, pady=(10, 0))
        ui.Texto(self, sub, 8, cor="mut").pack(anchor="w", padx=12)
        self.valor = ui.Texto(self, "—", 24, True)
        self.valor.pack(anchor="w", padx=12)
        self.barra = ui.Barra(self, aviso=aviso, perigo=perigo, largura=120)
        self.barra.pack(fill="x", padx=12, pady=(2, 12))

    def set(self, graus):
        self.valor.configure(text=f"{graus:.0f} °C", fg=ui.cor_nivel(graus, self.aviso, self.perigo))
        self.barra.set(graus)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Monitor PC")
        self.cfg = ler_config()
        self.minsize(960, 680)
        self.restaurar_janela()
        ui.aplicar_tema(self, "light" if self.cfg.get("tema") == "light" else "dark")

        self.sensores = []
        self.live = deque(maxlen=120)
        self.n = 0
        self.cards_temp = {}
        self._mut = []
        self._fim = False
        self.proc_data = []

        self.build_cabecalho()
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        self.build_resumo()
        self.aba_meupc = meupc.AbaMeuPC(self.nb)
        self.nb.add(self.aba_meupc, text="Meu PC")
        self.build_processos()
        self.aba_hist = abas_extra.AbaHistorico(self.nb)
        self.nb.add(self.aba_hist, text="Histórico")
        self.build_disco()
        self.nb.add(abas_extra.AbaLimpeza(self.nb), text="Limpeza")
        self.build_temps()
        self.build_drivers()
        self.nb.add(abas_extra.AbaSistema(self.nb, self.reiniciar_admin), text="Sistema")
        self.nb.bind("<<NotebookTabChanged>>", self.on_tab)
        self.build_status()

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
        threading.Thread(target=self._poll_sensores, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self.fechar)

        ui.restilizar(self)
        psutil.cpu_percent()
        self.tick()

    # ---------- cabeçalho / rodapé ----------
    def build_cabecalho(self):
        h = ttk.Frame(self, padding=(16, 12, 16, 0))
        h.pack(fill="x")
        ttk.Label(h, text="Monitor PC", font=(ui.FONTE, 20, "bold")).pack(side="left")
        papel = "Administrador" if abas_extra.is_admin() else "Usuário padrão"
        sub = ttk.Label(h, text=f"   {socket.gethostname()}  •  {papel}", foreground=ui.Tema.p()["mut"])
        sub.pack(side="left", pady=(8, 0))
        self._mut.append(sub)
        claro = ui.Tema.nome == "light"
        self.btn_tema = ttk.Button(h, text="☾  Tema escuro" if claro else "☀  Tema claro",
                                   command=self.alternar_tema)
        self.btn_tema.pack(side="right")

    def build_status(self):
        self.status = ttk.Label(self, text="", foreground=ui.Tema.p()["mut"], padding=(16, 4))
        self.status.pack(fill="x", side="bottom")
        self._mut.append(self.status)

    def alternar_tema(self):
        novo = "light" if ui.Tema.nome == "dark" else "dark"
        ui.aplicar_tema(self, novo)
        self.btn_tema["text"] = "☾  Tema escuro" if novo == "light" else "☀  Tema claro"
        for w in self._mut:
            w.configure(foreground=ui.Tema.p()["mut"])
        self.cfg["tema"] = novo
        salvar_config(self.cfg)

    # ---------- tamanho e posição da janela ----------
    def restaurar_janela(self):
        j = self.cfg.get("janela") or {}
        try:
            w, h = int(j["w"]), int(j["h"])
            x, y = int(j["x"]), int(j["y"])
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w, h = max(960, min(w, sw)), max(680, min(h, sh))
            if not (-w + 150 < x < sw - 150 and 0 <= y < sh - 100):  # fora da tela (monitor desligado)
                raise ValueError
            self.geometry(f"{w}x{h}+{x}+{y}")
        except (KeyError, TypeError, ValueError):
            self.geometry("1180x780")
        if j.get("maximizada"):
            try:
                self.state("zoomed")
            except tk.TclError:
                pass

    def salvar_janela(self):
        try:
            j = dict(self.cfg.get("janela") or {})
            if self.state() == "zoomed":
                j["maximizada"] = True  # mantém o último tamanho normal
            elif self.state() == "normal":
                j.update(w=self.winfo_width(), h=self.winfo_height(), x=self.winfo_x(), y=self.winfo_y(),
                         maximizada=False)
            self.cfg["janela"] = j
            salvar_config(self.cfg)
        except tk.TclError:
            pass

    # ---------- bandeja / ciclo de vida ----------
    def on_tab(self, _):
        if self.nb.select() == str(self.aba_meupc) and not self.aba_meupc.carregada:
            self.aba_meupc.carregar()
        elif self.nb.select() == str(self.aba_hist):
            self.aba_hist.atualizar()
        elif self.nb.select() == str(self.f_temps):
            self.render_temps()

    def alerta(self, titulo, msg):
        if self.icon:
            self.icon.notify(msg, titulo)

    def abrir(self):
        self.deiconify()
        self.lift()

    def fechar(self):
        self.salvar_janela()
        if self.icon:
            self.withdraw()
            if not self.avisou_bandeja:
                self.avisou_bandeja = True
                self.icon.notify("Continua coletando o histórico. Use o ícone para abrir ou sair.", "Monitor PC")
        else:
            self.sair()

    def sair(self):
        if self.winfo_viewable():  # janela escondida na bandeja mantém o que foi salvo ao fechar
            self.salvar_janela()
        self._fim = True
        self.coletor.parar()
        if self.icon:
            self.icon.stop()
        self.destroy()

    def reiniciar_admin(self):
        abas_extra.relancar_como_admin()
        self.sair()

    def _poll_sensores(self):
        while not self._fim:
            self.sensores = historico.ler_sensores()
            for _ in range(50):
                if self._fim:
                    return
                time.sleep(0.1)

    # ---------- Resumo ----------
    def _medidor(self, parent, titulo):
        c = ui.Cartao(parent)
        m = ui.Medidor(c, titulo)
        m.pack(padx=10, pady=8)
        return m, c

    def build_resumo(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="Resumo")
        self.f_resumo = f
        barra = ttk.Frame(f)
        barra.pack(fill="x", pady=(0, 8))
        ttk.Button(barra, text="⚙  Personalizar painel", command=self.personalizar).pack(side="right")
        linha = ttk.Frame(f)
        self.linha = linha
        self.m_cpu, c_cpu = self._medidor(linha, "CPU")
        self.m_ram, c_ram = self._medidor(linha, "Memória RAM")
        self.m_disco, c_disco = self._medidor(linha, "Disco C:")
        c = ui.Cartao(linha)
        ui.Texto(c, "Sistema", 12, True).pack(anchor="w", padx=16, pady=(14, 6))
        self.lb_sis = ui.Texto(c, "", 10, cor="mut")
        self.lb_sis.configure(justify="left")
        self.lb_sis.pack(anchor="w", padx=16)

        self.temp_box = ttk.Frame(f)
        self.temp_aviso = ui.Cartao(self.temp_box)
        self.temp_aviso.pack(fill="x")
        ui.Texto(self.temp_aviso,
                 "Temperaturas: abra a LibreHardwareMonitor como administrador e ligue "
                 "Options > Remote Web Server > Run para ver CPU, GPU e discos aqui.",
                 9, cor="mut").pack(anchor="w", padx=14, pady=12)

        cg = ui.Cartao(f)
        ui.Texto(cg, "CPU e RAM — últimos 2 minutos (passe o mouse)", 10, True).pack(anchor="w", padx=14, pady=(10, 0))
        self.g_live = ui.Grafico(cg, [(1, "CPU", "cpu"), (2, "RAM", "ram")], altura=150)
        self.g_live.pack(fill="both", expand=True, padx=8, pady=8)

        baixo = ttk.Frame(f)
        self.baixo = baixo
        cd = ui.Cartao(baixo)
        ui.Texto(cd, "Discos", 10, True).pack(anchor="w", padx=14, pady=(10, 4))
        self.box_discos = tk.Frame(cd)
        self.box_discos._estilo = ("card", None)
        self.box_discos.configure(bg=ui.Tema.p()["card"])
        self.box_discos.pack(fill="x", padx=14, pady=(0, 10))
        self.linhas_disco = {}
        ca = ui.Cartao(baixo)
        ui.Texto(ca, "Avisos", 10, True).pack(anchor="w", padx=14, pady=(10, 4))
        self.lb_avisos = ui.Texto(ca, "", 10)
        self.lb_avisos.configure(justify="left", anchor="w")
        self.lb_avisos.pack(anchor="w", padx=14, pady=(0, 10))

        esq, cheio = {"side": "left", "padx": (0, 12)}, {"side": "left", "fill": "both", "expand": True}
        self.blocos = {
            "cpu": (c_cpu, esq), "ram": (c_ram, esq), "disco_c": (c_disco, esq), "sistema": (c, cheio),
            "discos": (cd, {**cheio, "padx": (0, 12)}), "avisos": (ca, cheio),
        }
        self.linhas = [
            (linha, ["cpu", "ram", "disco_c", "sistema"], {"fill": "x"}),
            (self.temp_box, ["temps"], {"fill": "x", "pady": (12, 0)}),
            (cg, ["grafico"], {"fill": "both", "expand": True, "pady": (12, 0)}),
            (baixo, ["discos", "avisos"], {"fill": "x", "pady": (12, 0)}),
        ]
        self.aplicar_layout()

    def _visivel(self, chave):
        return self.cfg.get("visivel", {}).get(chave, True)

    def aplicar_layout(self):
        """Mostra só os blocos escolhidos pelo usuário no Resumo."""
        for cont, chaves, _ in self.linhas:
            cont.pack_forget()
            for k in chaves:
                if k in self.blocos:
                    self.blocos[k][0].pack_forget()
        for cont, chaves, opts in self.linhas:
            ativos = [k for k in chaves if self._visivel(k)]
            if not ativos:
                continue
            for k in ativos:
                if k in self.blocos:
                    w, o = self.blocos[k]
                    w.pack(**o)
            cont.pack(**opts)

    def personalizar(self):
        win = tk.Toplevel(self)
        win.title("Personalizar painel")
        win.transient(self)
        win.resizable(False, False)
        box = ttk.Frame(win, padding=20)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="O que mostrar no Resumo", font=(ui.FONTE, 13, "bold")).pack(anchor="w")
        ttk.Label(box, text="As mudanças valem na hora e ficam salvas.",
                  foreground=ui.Tema.p()["mut"]).pack(anchor="w", pady=(2, 12))
        vars_ = {}

        def mudou():
            self.cfg["visivel"] = {k: v.get() for k, v in vars_.items()}
            salvar_config(self.cfg)
            self.aplicar_layout()

        for chave, nome in BLOCOS:
            v = tk.BooleanVar(value=self._visivel(chave))
            vars_[chave] = v
            ttk.Checkbutton(box, text=nome, variable=v, command=mudou).pack(anchor="w", pady=3)

        def tudo():
            for v in vars_.values():
                v.set(True)
            mudou()

        linha = ttk.Frame(box)
        linha.pack(fill="x", pady=(14, 0))
        ttk.Button(linha, text="Mostrar tudo", command=tudo).pack(side="left")
        ttk.Button(linha, text="Fechar", style="Accent.TButton", command=win.destroy).pack(side="right")
        win.update_idletasks()
        win.geometry(f"+{self.winfo_rootx() + 80}+{self.winfo_rooty() + 80}")
        win.grab_set()

    def atualizar_resumo(self):
        p = ui.Tema.p()
        cpu = psutil.cpu_percent()
        vm = psutil.virtual_memory()
        self.m_cpu.set(cpu, f"{psutil.cpu_count()} threads")
        self.m_ram.set(vm.percent, f"{gb(vm.used)} de {gb(vm.total)}")
        avisos = []
        try:
            du = psutil.disk_usage("C:" + chr(92))
            self.m_disco.set(du.percent, f"livre {gb(du.free)}")
            if du.percent > 90:
                avisos.append((f"C: quase cheio (livre {gb(du.free)})", "bad"))
        except OSError:
            pass
        if vm.percent > 85:
            avisos.append(("RAM acima de 85%. Feche programas pesados.", "warn"))
        if cpu > 90:
            avisos.append(("CPU acima de 90%.", "warn"))
        for nome, graus, lim in self.temps_atuais():
            if graus >= lim:
                avisos.append((f"{nome} quente: {graus:.0f} °C", "bad"))
        self.live.append((time.time(), cpu, vm.percent, None))
        self.g_live.set_rows(list(self.live))

        self.lb_sis["text"] = (f"Ligado há {duracao(time.time() - psutil.boot_time())}\n"
                               f"Processos: {len(psutil.pids())}\n"
                               f"RAM livre: {gb(vm.available)}")
        if avisos:
            self.lb_avisos.configure(text="\n".join("⚠  " + t for t, _ in avisos),
                                     fg=p["bad"] if any(k == "bad" for _, k in avisos) else p["warn"])
        else:
            self.lb_avisos.configure(text="✓  Tudo certo por aqui", fg=p["ok"])
        if self.n % 5 == 0:
            self.atualizar_discos()
        self.atualizar_cards_temp()

    def atualizar_discos(self):
        for part in psutil.disk_partitions():
            if "cdrom" in part.opts or not part.fstype:
                continue
            try:
                u = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            if part.device not in self.linhas_disco:
                r = len(self.linhas_disco)
                a = ui.Texto(self.box_discos, part.device.rstrip("\\"), 10, True)
                a.grid(row=r, column=0, sticky="w", pady=3)
                b = ui.Barra(self.box_discos, largura=180)
                b.grid(row=r, column=1, padx=10)
                c = ui.Texto(self.box_discos, "", 9, cor="mut")
                c.grid(row=r, column=2, sticky="w")
                self.linhas_disco[part.device] = (b, c)
            b, c = self.linhas_disco[part.device]
            b.set(u.percent)
            c["text"] = f"{u.percent:.0f}% usado • livre {gb(u.free)} de {gb(u.total)}"

    # ---------- temperaturas (cartões do Resumo) ----------
    def temps_atuais(self):
        """[(nome, graus, limite de alerta)] a partir da LibreHardwareMonitor."""
        res = []
        for h, s, g, _, v in self.sensores:
            if g != "Temperatura" or v is None:
                continue
            if s == "CPU Package":
                res.append(("CPU", v, 85))
            elif s == "GPU Core":
                res.append(("GPU", v, 85))
            elif s == "Temperature":
                res.append((f"Disco {h.strip()}", v, 60))
        return res

    def atualizar_cards_temp(self):
        atuais = self.temps_atuais()
        if not atuais:
            if self.cards_temp:
                for c in self.cards_temp.values():
                    c.destroy()
                self.cards_temp = {}
            if not self.temp_aviso.winfo_ismapped():
                self.temp_aviso.pack(fill="x")
            return
        if self.temp_aviso.winfo_ismapped():
            self.temp_aviso.pack_forget()
        if set(self.cards_temp) != {n for n, _, _ in atuais}:
            for c in self.cards_temp.values():
                c.destroy()
            self.cards_temp = {}
            for nome, _, lim in atuais:
                disco = nome.startswith("Disco")
                card = CartaoTemp(self.temp_box, nome.split(" ")[0] if not disco else "Disco",
                                  nome[6:] if disco else "temperatura", 45 if disco else 65, lim if not disco else 55)
                card.pack(side="left", fill="x", expand=True, padx=(0, 10))
                self.cards_temp[nome] = card
        for nome, graus, _ in atuais:
            if nome in self.cards_temp:
                self.cards_temp[nome].set(graus)

    # ---------- Processos ----------
    def build_processos(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="Processos")
        topo = ttk.Frame(f)
        topo.pack(fill="x")
        ttk.Label(topo, text="Buscar:").pack(side="left")
        self.proc_filtro = tk.StringVar()
        self.proc_filtro.trace_add("write", lambda *_: self.render_procs())
        ttk.Entry(topo, textvariable=self.proc_filtro, width=28).pack(side="left", padx=6)
        ttk.Button(topo, text="Encerrar selecionado", command=self.kill_selected).pack(side="right")
        dica = ttk.Label(f, text="Soma de todos os processos de cada programa. Clique no cabeçalho para ordenar; "
                                 "clique com o botão direito para encerrar. Vermelho = mais de 1 GB.",
                         foreground=ui.Tema.p()["mut"])
        dica.pack(anchor="w", pady=(6, 4))
        self._mut.append(dica)
        frame, self.proc_tree = ui.criar_tree(f, ("Programa", "RAM", "CPU %", "Processos"), (320, 120, 90, 100))
        frame.pack(fill="both", expand=True)
        self.proc_tree._ordem = ("RAM", True)
        self.menu_proc = tk.Menu(self, tearoff=0)
        self.menu_proc.add_command(label="Encerrar todos os processos deste programa", command=self.kill_selected)
        self.proc_tree.bind("<Button-3>", self._menu_proc)

    def _menu_proc(self, e):
        iid = self.proc_tree.identify_row(e.y)
        if iid:
            self.proc_tree.selection_set(iid)
            self.menu_proc.tk_popup(e.x_root, e.y_root)

    def coletar_procs(self):
        grupos = defaultdict(lambda: [0, 0.0, 0])
        for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
            try:
                g = grupos[p.info["name"] or "?"]
                g[0] += p.info["memory_info"].rss
                g[1] += p.info["cpu_percent"] or 0
                g[2] += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
        nc = psutil.cpu_count() or 1
        self.proc_data = sorted(((n, m, c / nc, k) for n, (m, c, k) in grupos.items()),
                                key=lambda x: x[1], reverse=True)
        self.render_procs()

    def render_procs(self):
        t = self.proc_tree
        filtro = self.proc_filtro.get().strip().lower()
        sel = t.selection()
        manter = t.item(sel[0])["values"][0] if sel else None
        t.delete(*t.get_children())
        n = 0
        for nome, mem, cpu, cont in self.proc_data:
            if filtro and filtro not in nome.lower():
                continue
            iid = t.insert("", "end", values=(nome, mb(mem), f"{cpu:.1f}", cont),
                           tags=("heavy",) if mem >= 1024**3 else ())
            if str(nome) == str(manter):
                t.selection_set(iid)
            n += 1
            if n >= 80:
                break
        ui.reordenar(t)

    def kill_selected(self):
        sel = self.proc_tree.selection()
        if not sel:
            return
        nome = str(self.proc_tree.item(sel[0])["values"][0])
        if not messagebox.askyesno("Confirmar", f"Encerrar TODOS os processos '{nome}'?"):
            return
        for p in psutil.process_iter(["name"]):
            if p.info["name"] == nome:
                try:
                    p.terminate()
                except Exception:
                    pass

    # ---------- Disco ----------
    def build_disco(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="Disco")
        ttk.Label(f, text="Analisador de pastas", font=(ui.FONTE, 13, "bold")).pack(anchor="w")
        sub = ttk.Label(f, text="Mostra as maiores subpastas e arquivos. Só lê, não apaga nada. "
                                "Dois cliques em uma linha abrem a pasta no Explorer.",
                        foreground=ui.Tema.p()["mut"])
        sub.pack(anchor="w", pady=(0, 8))
        self._mut.append(sub)
        top = ttk.Frame(f)
        top.pack(fill="x")
        self.scan_path = tk.StringVar(value=os.path.expanduser("~"))
        ttk.Entry(top, textvariable=self.scan_path, width=52).pack(side="left")
        ttk.Button(top, text="Escolher...", command=lambda: self.scan_path.set(
            filedialog.askdirectory() or self.scan_path.get())).pack(side="left", padx=6)
        self.scan_btn = ttk.Button(top, text="Analisar", style="Accent.TButton", command=self.start_scan)
        self.scan_btn.pack(side="left")
        self.scan_prog = ttk.Progressbar(top, mode="indeterminate", length=120)
        atalhos = ttk.Frame(f)
        atalhos.pack(fill="x", pady=8)
        ttk.Label(atalhos, text="Atalhos:").pack(side="left")
        for nome, caminho in (("Usuário", os.path.expanduser("~")),
                              ("AppData", os.path.join(os.path.expanduser("~"), "AppData")),
                              ("C:\\", "C:" + chr(92)),
                              ("Steam", r"C:\Program Files (x86)\Steam"),
                              ("Program Files", r"C:\Program Files")):
            ttk.Button(atalhos, text=nome, command=lambda c=caminho: self.scan_path.set(c)).pack(side="left", padx=3)
        self.scan_lbl = ttk.Label(f, text="", foreground=ui.Tema.p()["mut"])
        self.scan_lbl.pack(anchor="w")
        self._mut.append(self.scan_lbl)
        frame, self.disk_tree = ui.criar_tree(f, ("Pasta", "Tamanho", "Proporção"), (560, 110, 220))
        frame.pack(fill="both", expand=True, pady=(4, 0))
        self.disk_tree.bind("<Double-1>", self.open_folder)

    def open_folder(self, _):
        sel = self.disk_tree.selection()
        if sel:
            caminho = self.disk_tree.item(sel[0])["values"][0]
            os.startfile(caminho if os.path.isdir(caminho) else os.path.dirname(caminho))

    def start_scan(self):
        self.scan_btn.state(["disabled"])
        self.scan_prog.pack(side="left", padx=10)
        self.scan_prog.start(12)
        self.scan_lbl["text"] = "Analisando... pode levar alguns minutos."
        self.disk_tree.delete(*self.disk_tree.get_children())
        threading.Thread(target=self.scan, args=(self.scan_path.get(),), daemon=True).start()

    def scan(self, raiz):
        res = []
        try:
            with os.scandir(raiz) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            res.append((e.path, abas_extra.tamanho_pasta(e.path)))
                        else:
                            res.append((e.path, e.stat().st_size))
                    except OSError:
                        pass
        except OSError:
            pass
        res.sort(key=lambda x: x[1], reverse=True)
        self.after(0, self.show_scan, res[:80])

    def show_scan(self, res):
        maior = res[0][1] if res and res[0][1] else 1
        for caminho, tam in res:
            barra = "█" * max(1, round(22 * tam / maior)) if tam else ""
            self.disk_tree.insert("", "end", values=(caminho, abas_extra.fmt(tam), barra),
                                  tags=("heavy",) if tam >= 10 * 1024**3 else ())
        self.disk_tree._ordem = ("Tamanho", True)
        ui.reordenar(self.disk_tree)
        total = sum(t for _, t in res)
        self.scan_lbl["text"] = f"Pronto. {len(res)} itens, total {abas_extra.fmt(total)}. Vermelho = mais de 10 GB."
        self.scan_prog.stop()
        self.scan_prog.pack_forget()
        self.scan_btn.state(["!disabled"])

    # ---------- Temperaturas (tabela completa) ----------
    def build_temps(self):
        f = ttk.Frame(self.nb, padding=12)
        self.f_temps = f
        self.nb.add(f, text="Temperaturas")
        ttk.Label(f, text="Sensores", font=(ui.FONTE, 13, "bold")).pack(anchor="w")
        top = ttk.Frame(f)
        top.pack(fill="x", pady=(6, 6))
        ttk.Label(top, text="Buscar:").pack(side="left")
        self.temp_filtro = tk.StringVar()
        self.temp_filtro.trace_add("write", lambda *_: self.render_temps())
        ttk.Entry(top, textvariable=self.temp_filtro, width=24).pack(side="left", padx=6)
        self.temp_lbl = ttk.Label(top, text="", foreground=ui.Tema.p()["mut"])
        self.temp_lbl.pack(side="left", padx=8)
        self._mut.append(self.temp_lbl)
        frame, self.temp_tree = ui.criar_tree(f, ("Hardware", "Sensor", "Tipo", "Valor"), (260, 260, 110, 110))
        frame.pack(fill="both", expand=True)

    def render_temps(self):
        sens = self.sensores
        t = self.temp_tree
        t.delete(*t.get_children())
        if not sens:
            self.temp_lbl["text"] = ("Sem dados. Abra a LibreHardwareMonitor como administrador e ligue "
                                     "Options > Remote Web Server > Run.")
            return
        filtro = self.temp_filtro.get().strip().lower()
        for h, s, g, txt, v in sens:
            if filtro and filtro not in f"{h} {s} {g}".lower():
                continue
            tag = ()
            if g == "Temperatura" and v is not None:
                tag = ("heavy",) if v >= 85 else ("warn",) if v >= 70 else ()
            t.insert("", "end", values=(h, s, g, txt), tags=tag)
        ui.reordenar(t)
        self.temp_lbl["text"] = "Atualiza sozinho a cada poucos segundos. Amarelo ≥ 70 °C, vermelho ≥ 85 °C."

    # ---------- Drivers ----------
    def build_drivers(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="Drivers")
        ttk.Label(f, text="Drivers instalados", font=(ui.FONTE, 13, "bold")).pack(anchor="w")
        top = ttk.Frame(f)
        top.pack(fill="x", pady=(6, 6))
        ttk.Button(top, text="Listar drivers", style="Accent.TButton", command=self.list_drivers).pack(side="left")
        ttk.Button(top, text="Abrir Windows Update",
                   command=lambda: os.startfile("ms-settings:windowsupdate")).pack(side="left", padx=6)
        ttk.Label(top, text="Buscar:").pack(side="left", padx=(12, 0))
        self.drv_filtro = tk.StringVar()
        self.drv_filtro.trace_add("write", lambda *_: self.render_drivers())
        ttk.Entry(top, textvariable=self.drv_filtro, width=22).pack(side="left", padx=6)
        self.drv_lbl = ttk.Label(f, text="Amarelo = driver com mais de 5 anos.", foreground=ui.Tema.p()["mut"])
        self.drv_lbl.pack(anchor="w")
        self._mut.append(self.drv_lbl)
        frame, self.drv_tree = ui.criar_tree(f, ("Dispositivo", "Fabricante", "Versão", "Data"), (320, 220, 140, 100))
        frame.pack(fill="both", expand=True, pady=(4, 0))
        self.drv_data = []

    def list_drivers(self):
        self.drv_lbl["text"] = "Lendo..."
        threading.Thread(target=self._drivers_worker, daemon=True).start()

    def _drivers_worker(self):
        cmd = ("Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceName -and $_.DriverDate } "
               "| Sort-Object DriverDate | Select-Object -First 200 DeviceName,Manufacturer,DriverVersion,"
               "@{n='Date';e={$_.DriverDate.ToString('yyyy-MM-dd')}} | ConvertTo-Json")
        try:
            data = json.loads(ps(cmd) or "[]")
        except Exception:
            data = []
        self.drv_data = data
        self.after(0, self.render_drivers)

    def render_drivers(self):
        t = self.drv_tree
        t.delete(*t.get_children())
        filtro = self.drv_filtro.get().strip().lower()
        corte = time.localtime().tm_year - 5
        n = 0
        for d in self.drv_data:
            if filtro and filtro not in f"{d['DeviceName']} {d['Manufacturer']}".lower():
                continue
            velho = d["Date"][:4].isdigit() and int(d["Date"][:4]) <= corte
            t.insert("", "end", values=(d["DeviceName"], d["Manufacturer"], d["DriverVersion"], d["Date"]),
                     tags=("warn",) if velho else ())
            n += 1
        ui.reordenar(t)
        if self.drv_data:
            self.drv_lbl["text"] = f"{n} de {len(self.drv_data)} drivers (mais antigos primeiro). Amarelo = mais de 5 anos."

    # ---------- Loop ----------
    def tick(self):
        if self._fim:
            return
        if self.state() == "withdrawn":  # janela escondida na bandeja
            self.after(2000, self.tick)
            return
        self.atualizar_resumo()
        if self.n % 3 == 0:
            self.coletar_procs()
        if self.n % 3 == 1 and self.nb.select() == str(self.f_temps):
            self.render_temps()
        self.status["text"] = (f"Atualizado às {time.strftime('%H:%M:%S')}  •  histórico sendo gravado a cada 10 s  •  "
                               f"{'LibreHardwareMonitor conectada' if self.sensores else 'sem sensores de temperatura'}")
        self.n += 1
        self.after(1000, self.tick)


if __name__ == "__main__":
    App().mainloop()
