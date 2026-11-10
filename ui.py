"""Tema e componentes visuais do Monitor PC: medidor, barra, gráfico interativo, tabelas."""
import bisect
import re
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

try:
    import sv_ttk
except Exception:  # sem o pacote: usa o tema padrão do Tk
    sv_ttk = None

FONTE = "Segoe UI"

PALETAS = {
    "dark": dict(bg="#1c1c1c", card="#272727", fg="#f2f2f2", mut="#a0a0a0", grid="#3b3b3b",
                 acc="#60cdff", ok="#6ccb5f", warn="#fcc25c", bad="#ff6b6b",
                 cpu="#60cdff", ram="#fcb45c", tip_bg="#3d3d3d", tip_fg="#ffffff", zebra="#2b2b2b"),
    "light": dict(bg="#fafafa", card="#ffffff", fg="#1b1b1b", mut="#666666", grid="#dcdcdc",
                  acc="#0067c0", ok="#2e7d32", warn="#c77700", bad="#c62828",
                  cpu="#0067c0", ram="#d97706", tip_bg="#2b2b2b", tip_fg="#ffffff", zebra="#f5f5f5"),
}


class Tema:
    nome = "dark"

    @classmethod
    def p(cls):
        return PALETAS[cls.nome]


def cor_nivel(valor, aviso=60, perigo=85):
    p = Tema.p()
    return p["bad"] if valor >= perigo else p["warn"] if valor >= aviso else p["ok"]


def aplicar_tema(root, nome):
    Tema.nome = nome
    if sv_ttk:
        sv_ttk.set_theme(nome)
    st = ttk.Style(root)
    if not sv_ttk:  # sem o tema: garante que o estilo do botão de destaque exista
        st.layout("Accent.TButton", st.layout("TButton"))
    st.configure("Treeview", rowheight=26)
    st.configure("Treeview.Heading", font=(FONTE, 9, "bold"))
    st.configure("TNotebook.Tab", padding=(10, 6))
    root.configure(bg=Tema.p()["bg"])
    restilizar(root)


def restilizar(w):
    """Percorre os widgets e aplica as cores do tema atual."""
    p = Tema.p()
    est = getattr(w, "_estilo", None)
    if est:
        papel, cor_texto = est
        try:
            if isinstance(w, tk.Label):
                w.configure(bg=p[papel], fg=p[cor_texto or "fg"])
            else:
                w.configure(bg=p[papel])
            if getattr(w, "_borda", False):
                w.configure(highlightbackground=p["grid"], highlightcolor=p["grid"])
        except tk.TclError:
            pass
    if isinstance(w, ttk.Treeview):
        w.tag_configure("odd", background=p["zebra"])
        w.tag_configure("heavy", foreground=p["bad"])
        w.tag_configure("warn", foreground=p["warn"])
    if hasattr(w, "redesenhar"):
        w.redesenhar()
    for c in w.winfo_children():
        restilizar(c)


# ---------- peças básicas ----------
def Cartao(parent, **kw):
    f = tk.Frame(parent, bd=0, highlightthickness=1, **kw)
    f._estilo = ("card", None)
    f._borda = True
    f.configure(bg=Tema.p()["card"], highlightbackground=Tema.p()["grid"])
    return f


def Texto(parent, texto="", tam=10, negrito=False, cor="fg", fundo="card", **kw):
    lb = tk.Label(parent, text=texto, font=(FONTE, tam, "bold" if negrito else "normal"),
                  bd=0, **kw)
    lb._estilo = (fundo, cor)
    lb.configure(bg=Tema.p()[fundo], fg=Tema.p()[cor])
    return lb


class Barra(tk.Canvas):
    """Barra de progresso fina que muda de cor conforme o nível."""

    def __init__(self, master, aviso=60, perigo=85, altura=8, largura=160, fundo="card"):
        super().__init__(master, height=altura, width=largura, highlightthickness=0, bd=0)
        self._estilo = (fundo, None)
        self.configure(bg=Tema.p()[fundo])
        self.aviso, self.perigo, self.valor = aviso, perigo, 0.0
        self.bind("<Configure>", lambda e: self.redesenhar())

    def set(self, v):
        self.valor = max(0.0, min(100.0, v))
        self.redesenhar()

    def redesenhar(self):
        p = Tema.p()
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        self.create_rectangle(0, 0, w, h, fill=p["grid"], outline="")
        if self.valor > 0:
            self.create_rectangle(0, 0, w * self.valor / 100, h, outline="",
                                  fill=cor_nivel(self.valor, self.aviso, self.perigo))


class Medidor(tk.Canvas):
    """Medidor circular com animação suave."""

    def __init__(self, master, titulo, tamanho=170):
        super().__init__(master, width=tamanho, height=tamanho + 18, highlightthickness=0, bd=0)
        self._estilo = ("card", None)
        self.configure(bg=Tema.p()["card"])
        self.tam, self.titulo = tamanho, titulo
        self.valor = 0.0
        self.alvo = 0.0
        self.sub = ""
        self._anim = False

    def set(self, alvo, sub=""):
        self.alvo, self.sub = max(0.0, min(100.0, alvo)), sub
        if not self._anim:
            self._anim = True
            self._passo()

    def _passo(self):
        dif = self.alvo - self.valor
        if abs(dif) < 0.4:
            self.valor = self.alvo
            self._anim = False
        else:
            self.valor += dif * 0.3
            self.after(30, self._passo)
        self.redesenhar()

    def redesenhar(self):
        p = Tema.p()
        self.delete("all")
        s, m = self.tam, 16
        caixa = (m, m, s - m, s - m)
        self.create_arc(*caixa, start=225, extent=-270, style="arc", width=12, outline=p["grid"])
        if self.valor > 0.5:
            self.create_arc(*caixa, start=225, extent=-270 * self.valor / 100, style="arc",
                            width=12, outline=cor_nivel(self.valor))
        self.create_text(s / 2, s / 2 - 8, text=f"{self.valor:.0f}%", font=(FONTE, 26, "bold"), fill=p["fg"])
        self.create_text(s / 2, s / 2 + 22, text=self.titulo, font=(FONTE, 10), fill=p["mut"])
        self.create_text(s / 2, s + 6, text=self.sub, font=(FONTE, 9), fill=p["mut"])


class Grafico(tk.Canvas):
    """Gráfico de linhas com mouse por cima: linha-guia, pontos e caixa com detalhes."""

    ML, MR, MT, MB = 42, 14, 30, 24

    def __init__(self, master, series, altura=210, fmt_hora="%H:%M:%S", dica=None):
        super().__init__(master, height=altura, highlightthickness=0, bd=0)
        self._estilo = ("card", None)
        self.configure(bg=Tema.p()["card"])
        self.series = series          # [(índice na linha, rótulo, chave de cor)]
        self.fmt_hora, self.dica = fmt_hora, dica
        self.rows, self.pts, self.xs, self.hover = [], [], [], None
        self.fonte = tkfont.Font(family=FONTE, size=9)
        self.bind("<Configure>", lambda e: self.redesenhar())
        self.bind("<Motion>", self._mover)
        self.bind("<Leave>", self._sair)

    def set_rows(self, rows):
        self.rows = rows
        self.redesenhar()

    def _mover(self, e):
        if not self.xs:
            return
        i = bisect.bisect_left(self.xs, e.x)
        if i > 0 and (i == len(self.xs) or e.x - self.xs[i - 1] < self.xs[i] - e.x):
            i -= 1
        self.hover = min(i, len(self.xs) - 1)
        self.redesenhar()

    def _sair(self, _):
        self.hover = None
        self.redesenhar()

    def redesenhar(self):
        p = Tema.p()
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 80:
            return
        pw, ph = w - self.ML - self.MR, h - self.MT - self.MB
        for v in (0, 25, 50, 75, 100):
            y = self.MT + ph - ph * v / 100
            self.create_line(self.ML, y, w - self.MR, y, fill=p["grid"])
            self.create_text(self.ML - 6, y, text=f"{v}%", anchor="e", fill=p["mut"], font=(FONTE, 8))
        x = self.ML
        for _, rotulo, ck in self.series:
            self.create_rectangle(x, 10, x + 10, 20, fill=p[ck], outline="")
            self.create_text(x + 15, 15, text=rotulo, anchor="w", fill=p["fg"], font=(FONTE, 9, "bold"))
            x += 15 + self.fonte.measure(rotulo) + 22
        if len(self.rows) < 2:
            self.create_text(w / 2, h / 2, fill=p["mut"], font=(FONTE, 10),
                             text="Sem dados ainda. Deixe o programa aberto (ou na bandeja) para coletar.")
            self.xs = []
            return
        passo = max(1, len(self.rows) // max(pw, 1))
        pts = self.rows[::passo]
        if pts[-1] is not self.rows[-1]:
            pts.append(self.rows[-1])
        self.pts = pts
        t0, t1 = pts[0][0], pts[-1][0]
        span = max(t1 - t0, 1)
        self.xs = [self.ML + pw * (r[0] - t0) / span for r in pts]

        def y_de(v):
            return self.MT + ph - ph * max(0, min(v, 100)) / 100

        for idx, _, ck in self.series:
            coords = []
            for xx, r in zip(self.xs, pts):
                coords += [xx, y_de(r[idx])]
            if len(coords) >= 4:
                self.create_line(*coords, fill=p[ck], width=2)
        f = self.fmt_hora if (t1 - t0) < 86400 else "%d/%m %H:%M"
        self.create_text(self.ML, h - 10, text=time.strftime(f, time.localtime(t0)), anchor="w",
                         fill=p["mut"], font=(FONTE, 8))
        self.create_text(w - self.MR, h - 10, text=time.strftime(f, time.localtime(t1)), anchor="e",
                         fill=p["mut"], font=(FONTE, 8))
        if self.hover is not None and self.hover < len(pts):
            self._desenhar_dica(pts[self.hover], self.xs[self.hover], y_de, w, h)

    def _desenhar_dica(self, row, x, y_de, w, h):
        p = Tema.p()
        self.create_line(x, self.MT, x, h - self.MB, fill=p["mut"], dash=(3, 3))
        for idx, _, ck in self.series:
            y = y_de(row[idx])
            self.create_oval(x - 4, y - 4, x + 4, y + 4, fill=p[ck], outline=p["card"], width=2)
        if self.dica:
            linhas = self.dica(row)
        else:
            linhas = [time.strftime(self.fmt_hora, time.localtime(row[0]))] + \
                     [f"{rot}: {row[idx]:.0f}%" for idx, rot, _ in self.series]
        lw = max(self.fonte.measure(l) for l in linhas) + 16
        lh = len(linhas) * 17 + 10
        bx = x + 14 if x + 14 + lw < w - 4 else x - 14 - lw
        by = self.MT + 4
        self.create_rectangle(bx, by, bx + lw, by + lh, fill=p["tip_bg"], outline=p["grid"])
        for i, l in enumerate(linhas):
            self.create_text(bx + 8, by + 8 + i * 17, text=l, anchor="nw", fill=p["tip_fg"],
                             font=(FONTE, 9, "bold" if i == 0 else "normal"))


class AreaRolavel(ttk.Frame):
    """Área com rolagem (barra + roda do mouse). Coloque os widgets em `.interior`."""

    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.canvas._estilo = ("bg", None)
        self.canvas.configure(bg=Tema.p()["bg"])
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.interior = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")
        self.interior.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._roda))
        self.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _roda(self, e):
        if self.interior.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 * (e.delta // 120), "units")


# ---------- tabelas ----------
def _chave(txt):
    s = str(txt).strip()
    m = re.fullmatch(r"([\d.,]+)\s*(GB|MB|KB|%|°C|RPM)?", s)
    if m:
        try:
            n = float(m.group(1).replace(",", "."))
            return (0, n * {"GB": 1024, "MB": 1, "KB": 1 / 1024}.get(m.group(2), 1), "")
        except ValueError:
            pass
    return (1, 0, s.lower())


def zebra(tree):
    for i, iid in enumerate(tree.get_children("")):
        tags = [t for t in tree.item(iid, "tags") if t != "odd"]
        if i % 2:
            tags.append("odd")
        tree.item(iid, tags=tags)


def reordenar(tree):
    ordem = getattr(tree, "_ordem", None)
    if ordem:
        col, reverso = ordem
        itens = sorted(((tree.set(i, col), i) for i in tree.get_children("")),
                       key=lambda x: _chave(x[0]), reverse=reverso)
        for pos, (_, iid) in enumerate(itens):
            tree.move(iid, "", pos)
    zebra(tree)


def criar_tree(parent, cols, larguras, altura=None):
    """Tabela com cabeçalho clicável (ordena) e barra de rolagem."""
    frame = ttk.Frame(parent)
    kw = {"height": altura} if altura else {}
    tree = ttk.Treeview(frame, columns=cols, show="headings", **kw)
    tree._ordem = None

    def clicar(col):
        atual = tree._ordem
        reverso = not atual[1] if atual and atual[0] == col else False
        tree._ordem = (col, reverso)
        for c in cols:
            seta = (" ▼" if reverso else " ▲") if c == col else ""
            tree.heading(c, text=c + seta)
        reordenar(tree)

    for c, w in zip(cols, larguras):
        tree.heading(c, text=c, command=lambda c=c: clicar(c))
        tree.column(c, width=w, anchor="w")
    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    tree.tag_configure("odd", background=Tema.p()["zebra"])
    tree.tag_configure("heavy", foreground=Tema.p()["bad"])
    tree.tag_configure("warn", foreground=Tema.p()["warn"])
    return frame, tree
