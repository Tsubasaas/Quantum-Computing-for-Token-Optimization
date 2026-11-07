"""ワークスペース画面の見た目（UI 実装プロンプト §3 / 付録B の再現）。

色・角丸・フォントの大半は ``.streamlit/config.toml`` 側で指定している。ここに
書くのは config.toml で表せないもの — 濃紺ヘッダー、進行ステップ、カテゴリ 3 色、
STEP 段組みのワークフロー — だけに絞る。

Streamlit のコンテナは ``key`` を付けると ``.st-key-<key>`` クラスが付くので、
セレクタはその接頭辞（``qopanel`` / ``qocat`` / ``qoplan``）で当てている。

本モジュールは全体が生成 AI（Claude）支援で作成されています。
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

import streamlit as st

__all__ = [
    "CATEGORY_LABELS",
    "inject_css",
    "render_header",
    "render_steps",
    "render_section_nav",
    "section_anchor",
    "eyebrow",
    "section_head",
    "tag",
    "node_html",
    "workflow_html",
    "dependency_tree_dot",
    "esc",
]

# 仕様 §3.2。色だけで区別させないため、バッジには必ずカテゴリ名も出す。
CATEGORY_LABELS: dict[str, str] = {
    "doc": "文書作成",
    "code": "開発・プログラミング",
    "image": "画像生成",
}

_CSS = """
<style>
/* ---- レイアウト（§3.1） ---------------------------------------------- */
.stMainBlockContainer {
  max-width: 1280px;
  padding-top: 0;
  padding-bottom: 3rem;
}
.stApp [data-testid="stHeader"] { background: transparent; }

/* ---- 濃紺ヘッダー（§4.A） -------------------------------------------- */
.qo-header {
  position: relative;
  left: 50%;
  width: 100vw;
  margin-left: -50vw;
  margin-bottom: 22px;
  background: #102a43;
  color: #fff;
}
.qo-header-inner {
  max-width: 1280px;
  margin: 0 auto;
  padding: 19px 28px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.qo-brand { display: flex; gap: 22px; align-items: center; min-width: 0; }
.qo-logo { width: clamp(180px, 24vw, 290px); flex-shrink: 0; }
.qo-logo img { display: block; width: 100%; height: auto; }
.qo-brand-name { font-size: 20px; font-weight: 650; letter-spacing: 0.04em; }
.qo-brand-caption { color: #a6c7d3; font-size: 12px; margin-top: 5px; }
.qo-badge {
  font-size: 13px;
  background: #294960;
  color: #fff;
  padding: 6px 12px;
  border-radius: 20px;
  white-space: nowrap;
}
.qo-badge.light { background: #e7f2f4; color: #087680; }

/* ---- 進行ステップ（§4.A） -------------------------------------------- */
.qo-steps { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 22px; }
.qo-steps span {
  padding: 8px 16px;
  border-radius: 20px;
  background: #dfe9ef;
  color: #46617a;
  font-size: 14px;
}
.qo-steps span.on { background: #087e8b; color: #fff; }

/* ---- セクションショートカット ---------------------------------------- */
/* 左に固定の目次。画面が広いときは左側の余白をしっかり使う。 */
@media (min-width: 1101px) {
  .stMainBlockContainer {
    max-width: 1560px;
  }
}
/* 目次を置く余白が取れない幅では隠す（本文に被せない）。 */
@media (max-width: 1100px) {
  .qo-section-nav { display: none; }
}
.qo-section-nav {
  position: fixed;
  z-index: 999;
  top: 88px;
  left: max(20px, calc(50vw - 780px));
  width: 258px;
  padding: 20px 18px;
  border: 1px solid #d7e3ea;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.97);
  box-shadow: 0 10px 30px rgba(16, 42, 67, 0.11);
  backdrop-filter: blur(8px);
  transition: transform 180ms ease;
}
.qo-section-nav-toggle {
  display: block;
  margin: 0 0 12px auto;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: #46617a;
  font: inherit;
  font-size: 26px;
  font-weight: 400;
  line-height: 1;
  cursor: pointer;
}
.qo-section-nav-toggle:hover,
.qo-section-nav-toggle:focus-visible {
  background: #e9f5f6;
  color: #075f68;
}
.qo-section-nav.is-collapsed {
  transform: translateX(calc(-100% + 44px));
}
.qo-section-nav.is-collapsed .qo-section-nav-content { display: none; }
.qo-section-nav-title {
  margin: 0 0 12px;
  padding-left: 4px;
  color: #596e7f;
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 1.6px;
}
.qo-section-nav a,
.qo-section-nav span {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 46px;
  padding: 11px 13px;
  border-left: 3px solid transparent;
  border-radius: 9px;
  color: #294960;
  font-size: 15px;
  line-height: 1.3;
  text-decoration: none;
}
.qo-section-nav a:hover,
.qo-section-nav a:focus-visible {
  color: #075f68;
  background: #e9f5f6;
  outline: none;
}
/* 今見ているセクション。ホバーより強く、選択中だと分かる見た目にする。 */
.qo-section-nav a.active {
  border-left-color: #087e8b;
  background: #dff0f2;
  color: #06545c;
  font-weight: 700;
}
.qo-section-nav a.active .qo-section-nav-index { color: #06545c; }
.qo-section-nav span.disabled { color: #9aa9b5; cursor: not-allowed; }
.qo-section-nav-index {
  flex: 0 0 auto;
  width: 26px;
  color: #087e8b;
  font-size: 13px;
  font-weight: 800;
}
.qo-section-nav span.disabled .qo-section-nav-index { color: #aeb9c1; }
.qo-section-anchor {
  position: relative;
  top: -18px;
  height: 0;
  scroll-margin-top: 22px;
  visibility: hidden;
}

/* ---- 白パネル（§3.1） ------------------------------------------------- */
[class*="st-key-qopanel"] {
  background: #fff;
  border: 1px solid #dce6ec;
  border-radius: 12px;
  padding: 26px;
  margin-bottom: 22px;
}
[class*="st-key-qopanel"] > div > [data-testid="stVerticalBlockBorderWrapper"] { border: 0; }

.qo-eyebrow {
  font-size: 12px;
  letter-spacing: 2px;
  color: #087e8b;
  font-weight: 750;
  margin-bottom: 2px;
}
.qo-muted { color: #596e7f; font-size: 14px; }
.qo-headrow {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
}

/* ---- カテゴリ選択カード（§4.B） --------------------------------------- */
[class*="st-key-qocat-"] {
  border: 1px solid #cbdce6;
  border-radius: 8px;
  padding: 14px;
  background: #fff;
  height: 100%;
}
[class*="st-key-qocat-"]:has(.qo-on) { background: #f0f8fa; border-color: #087e8b; }
.qo-cat-hint { display: block; font-size: 13px; color: #596e7f; margin: 2px 0 0 30px; }

/* ---- プラン比較カード（§4.D） ----------------------------------------- */
[class*="st-key-qoplan-"] {
  background: #fff;
  border: 2px solid #dce6ec;
  border-radius: 10px;
  padding: 22px;
  height: 100%;
}
[class*="st-key-qoplan-"]:has(.qo-on) { border-color: #087e8b; background: #effafb; }
[class*="st-key-qoplan-"]:has(.qo-infeasible) { border-color: #e6c4bd; background: #fdf6f5; }
/* 目安上限の超過は「実行できない」ではない。枠だけ色を変え、背景は白のまま残す。 */
[class*="st-key-qoplan-"]:has(.qo-overcap) { border-color: #e6c4bd; }
[class*="st-key-qoplan-"]:has(.qo-on):has(.qo-overcap) { border-color: #087e8b; }
[class*="st-key-qoplan-"] .stButton button { width: 100%; }
.qo-plan-name { font-size: 17px; font-weight: 700; margin-bottom: 2px; }
.qo-price { font-size: 34px; font-weight: 750; color: #087e8b; line-height: 1.2; }
.qo-price.na { color: #a63525; font-size: 22px; }
/* 目安上限を超えた費用。桁を読み違えないよう、サイズは通常時と同じに保つ。 */
.qo-price.over { color: #a63525; }
.qo-note {
  color: #a63525;
  background: #fdf6f5;
  border-radius: 6px;
  padding: 8px 10px;
  margin: 10px 0 2px;
  font-size: 13px;
  line-height: 1.5;
}
.qo-metric {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  border-bottom: 1px solid #dfe8ed;
  padding: 7px 0;
  font-size: 14px;
}
.qo-metric span:last-child { font-weight: 650; text-align: right; }
.qo-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 12px; }

/* ---- カテゴリ 3 色（§3.2） -------------------------------------------- */
.qo-tag {
  padding: 3px 9px;
  border-radius: 5px;
  font-size: 12px;
  display: inline-block;
  background: #e7edf3;
  color: #46617a;
}
.qo-tag.doc { background: #e6f3f6; color: #096d7a; }
.qo-tag.code { background: #edf0ff; color: #414da0; }
.qo-tag.image { background: #fff1e5; color: #9a521b; }

/* ---- ワークフロー（§4.E） --------------------------------------------- */
.qo-workflow { margin: 18px 0; }
.qo-level { display: grid; grid-template-columns: 80px 1fr; gap: 14px; }
.qo-levelnum { font-size: 12px; color: #627586; padding-top: 15px; }
.qo-nodes {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.qo-node {
  padding: 15px;
  border: 1px solid #d4e4eb;
  border-left: 4px solid #087e8b;
  border-radius: 6px;
  background: #f7fafc;
}
.qo-node.code { border-left-color: #5d68ac; }
.qo-node.image { border-left-color: #bb733c; }
.qo-node b { display: block; font-size: 15px; margin: 6px 0; }
.qo-node small { display: block; font-size: 13px; color: #526b7c; }
.qo-node.running { outline: 2px solid #cb932e; }
.qo-node.done { background: #e6f5ef; }
.qo-node .qo-state { font-weight: 650; }
.qo-node { outline: 2px solid transparent; transition: background .12s, outline-color .12s; }
.qo-workflow .qo-node:hover { background: #eef6f8; outline-color: #087e8b; }

/* ---- 補助（§3.3） ----------------------------------------------------- */
.qo-error { color: #a63525; font-size: 14px; }
.qo-success { padding: 17px; background: #e6f5ef; border-radius: 8px; }
.qo-solver-alert {
  padding: 15px 18px;
  margin: 0 0 18px;
  border: 1px solid #e1a3a3;
  border-left: 5px solid #c93636;
  border-radius: 10px;
  background: #fff1f1;
  color: #5f2020;
}
.qo-solver-alert-title { display: flex; align-items: center; gap: 8px; }
.qo-solver-alert-icon {
  display: inline-flex;
  width: 22px;
  height: 22px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #c93636;
  color: #fff;
  font-weight: 800;
  line-height: 1;
}
.qo-solver-alert strong { color: #a32222; }
.qo-solver-alert-detail,
.qo-solver-alert-error { margin: 7px 0 0; font-size: 14px; line-height: 1.55; }
.qo-solver-alert-error {
  padding-top: 8px;
  border-top: 1px solid #e8baba;
  color: #8a2525;
  overflow-wrap: anywhere;
}
/* 選択状態のマーカー。:has() の対象にするだけで、レイアウトには出さない。
   独立した要素にはせず、カード内の既存 HTML へ同梱している（要素を足すと高さがずれる）。 */
.qo-on, .qo-infeasible, .qo-overcap { display: none; }
.stButton button:focus-visible, .stLinkButton a:focus-visible {
  outline: 3px solid #d69420;
  outline-offset: 3px;
}
.stProgress > div > div > div > div { background-color: #087e8b; }

/* ---- モバイル（§10） --------------------------------------------------- */
@media (max-width: 800px) {
  .qo-header-inner { padding: 16px; flex-wrap: wrap; }
  .qo-brand { gap: 14px; flex-wrap: wrap; }
  .qo-brand-name { font-size: 17px; }
  .qo-badge { white-space: normal; }
  [class*="st-key-qopanel"] { padding: 18px; }
  .qo-level { grid-template-columns: 1fr; gap: 0; }
  .qo-levelnum { padding: 0 0 7px; }
  .qo-nodes { grid-template-columns: 1fr; }
  .qo-steps { gap: 5px; }
  .qo-steps span { padding: 6px 10px; }
}
@media (max-width: 1100px) {
  .qo-section-nav {
    position: sticky;
    top: 8px;
    left: auto;
    width: auto;
    margin: 0 0 16px;
    padding: 8px;
    display: flex;
    gap: 4px;
    overflow-x: auto;
  }
  .qo-section-nav-title { display: none; }
  .qo-section-nav a,
  .qo-section-nav span { flex: 0 0 auto; min-height: 30px; white-space: nowrap; }
}
</style>
"""


def esc(text: object) -> str:
    """HTML へ差し込む前のエスケープ。タスク名は利用者が自由に書けるため必須。"""

    return html.escape(str(text), quote=True)


def inject_css() -> None:
    """デザインシステムの CSS を 1 回だけ流し込む。"""

    st.html(_CSS)


def render_header(*, badge: str) -> None:
    """濃紺ヘッダー。``badge`` には接続状態をそのまま出す（空なら非表示）。"""

    badge_html = f'<span class="qo-badge">{esc(badge)}</span>' if badge else ""
    logo = base64.b64encode(
        (Path(__file__).parent / "assets" / "yakizakana.svg").read_bytes()
    ).decode("ascii")
    st.html(
        '<div class="qo-header"><div class="qo-header-inner">'
        '<div class="qo-brand"><div class="qo-logo">'
        f'<img src="data:image/svg+xml;base64,{logo}" '
        'alt="ヤキザカナ — キの文字を魚に見立てたロゴ" width="290" height="97"></div>'
        '<div><div class="qo-brand-name">Yakizakanaヤキザカナ</div>'
        '<div class="qo-brand-caption">量子×AI、最適な実行プランへ</div></div></div>'
        f"{badge_html}</div></div>"
    )


def render_steps(current: int) -> None:
    """01〜04 の進行表示。``current`` まで青緑。ページ切り替えタブではない。"""

    labels = ["01 要望", "02 タスク", "03 プラン", "04 実行"]
    spans = "".join(
        f'<span class="{"on" if i <= current else ""}">{label}</span>'
        for i, label in enumerate(labels, start=1)
    )
    st.html(f'<div class="qo-steps">{spans}</div>')


# 今見ているセクションの項目に .active を付ける（スクロール追従）。
#
# CSS だけでは「スクロール位置で別要素を強調する」ができないため、ここだけ JS を使う。
# ``st.html`` は iframe を挟まず本体の DOM に挿入されるので、``unsafe_allow_javascript``
# を有効にすればアンカーの位置をそのまま測れる。差し込む HTML は自前の文字列のみ
# （ラベルは ``esc`` 済み）で、利用者入力は入らない。
# Streamlit は再実行のたびにこの要素を描き直すので、前回のリスナーを stop() で捨てる。
_SECTION_SPY_JS = """
<script>
(function () {
  var KEY = "__qoSectionSpy";
  if (window[KEY] && window[KEY].stop) { window[KEY].stop(); }

  function update() {
    var nav = document.querySelector(".qo-section-nav");
    if (!nav) { return; }
    var links = Array.prototype.slice.call(nav.querySelectorAll('a[href^="#"]'));
    if (!links.length) { return; }
    var current = null;
    for (var i = 0; i < links.length; i++) {
      var id = links[i].getAttribute("href").slice(1);
      var target = document.getElementById(id);
      if (!target) { continue; }
      // ヘッダーぶん下げた位置より上に来たセクションを「今見ている」とみなす。
      if (target.getBoundingClientRect().top <= 140) { current = links[i]; }
    }
    if (!current) { current = links[0]; }
    for (var j = 0; j < links.length; j++) {
      links[j].classList.toggle("active", links[j] === current);
    }
  }

  function setCollapsed(nav, collapsed) {
    nav.classList.toggle("is-collapsed", collapsed);
    var toggle = nav.querySelector(".qo-section-nav-toggle");
    if (!toggle) { return; }
    toggle.textContent = collapsed ? "\u203a" : "\u2039";
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute("aria-label", collapsed ? "セクションメニューを開く" : "セクションメニューを閉じる");
    toggle.setAttribute("title", collapsed ? "セクションメニューを開く" : "セクションメニューを閉じる");
  }

  function onToggle(event) {
    var toggle = event.target.closest(".qo-section-nav-toggle");
    if (!toggle) { return; }
    var nav = toggle.closest(".qo-section-nav");
    if (nav) { setCollapsed(nav, !nav.classList.contains("is-collapsed")); }
  }

  var queued = false;
  function onScroll() {
    if (queued) { return; }
    queued = true;
    window.requestAnimationFrame(function () { queued = false; update(); });
  }

  // Streamlit が内側の要素をスクロールさせる場合もあるので capture で拾う。
  window.addEventListener("scroll", onScroll, true);
  window.addEventListener("resize", onScroll);
  var nav = document.querySelector(".qo-section-nav");
  if (nav) {
    nav.addEventListener("click", onToggle);
    setCollapsed(nav, false);
  }
  window[KEY] = {
    stop: function () {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
      if (nav) { nav.removeEventListener("click", onToggle); }
    }
  };
  update();
})();
</script>
"""


def render_section_nav(items: list[tuple[str, str, bool]]) -> None:
    """画面左に固定するセクション目次。

    ``items`` は ``(anchor_id, label, enabled)``。未到達セクションはリンクにせず、
    これから表示される場所だと分かるよう薄く表示する。スクロールに追従して、
    今見ているセクションの項目に ``.active`` が付く。
    """

    links: list[str] = []
    for index, (anchor_id, label, enabled) in enumerate(items, start=1):
        content = f'<b class="qo-section-nav-index">{index:02d}</b>{esc(label)}'
        if enabled:
            links.append(f'<a href="#{esc(anchor_id)}">{content}</a>')
        else:
            links.append(
                f'<span class="disabled" aria-disabled="true">{content}</span>'
            )
    toggle = (
        '<button type="button" class="qo-section-nav-toggle" aria-expanded="true" '
        'aria-label="セクションメニューを閉じる" title="セクションメニューを閉じる">'
        "&lsaquo;</button>"
    )
    st.html(
        '<nav class="qo-section-nav" aria-label="セクションショートカット">'
        + toggle
        + '<div class="qo-section-nav-content"><div class="qo-section-nav-title">SECTION MENU</div>'
        + "".join(links)
        + "</div>"
        + "</nav>"
        + _SECTION_SPY_JS,
        unsafe_allow_javascript=True,
    )


def section_anchor(anchor_id: str) -> None:
    """固定ナビゲーションのリンク先を描画する。"""

    st.html(f'<div id="{esc(anchor_id)}" class="qo-section-anchor"></div>')


def eyebrow(text: str) -> str:
    return f'<div class="qo-eyebrow">{esc(text)}</div>'


def section_head(
    eyebrow_text: str, title: str, right: str = "", *, level: int = 2
) -> None:
    """英語の小見出し + 見出し + 右肩の補足を 1 行で描く。"""

    right_html = f'<div class="qo-muted">{esc(right)}</div>' if right else ""
    st.html(
        '<div class="qo-headrow"><div>'
        f"{eyebrow(eyebrow_text)}"
        f"<h{level} style='margin:4px 0 10px'>{esc(title)}</h{level}>"
        f"</div>{right_html}</div>"
    )


def tag(category: str) -> str:
    """カテゴリバッジ。色だけでなく必ず名前も出す（§3.2）。"""

    label = CATEGORY_LABELS.get(category, category)
    return f'<span class="qo-tag {esc(category)}">{esc(label)}</span>'


def node_html(
    *,
    display_id: str,
    category: str,
    title: str,
    model: str,
    depends_on: str,
    cost: str,
    extra: str = "",
    state: str = "",
) -> str:
    """ワークフロー 1 ノード。``state`` は "" / "running" / "done"。"""

    state_line = (
        f'<small class="qo-state">{esc(state_label(state))}</small>' if state else ""
    )
    extra_line = f"<small>{esc(extra)}</small>" if extra else ""
    return (
        f'<div class="qo-node {esc(category)} {esc(state)}" data-task="{esc(display_id)}">'
        f"<small>{esc(display_id)}　{tag(category)}</small>"
        f"<b>{esc(title)}</b>"
        f"<small>担当: {esc(model)}</small>"
        f"<small>前提: {esc(depends_on)}</small>"
        f"<small>費用: {esc(cost)}</small>"
        f"{extra_line}{state_line}</div>"
    )


def state_label(state: str) -> str:
    return {
        "running": "実行中…",
        "done": "完了",
        "blocked": "前提未完了",
        "failed": "失敗",
    }.get(state, "")


def workflow_html(
    levels_html: list[str], deps_by_task: dict[str, list[str]] | None = None
) -> str:
    """STEP 段組みをまとめる。``levels_html`` は段ごとのノード HTML 連結済み文字列。

    ``deps_by_task`` を渡すと、あるノードにホバーしたとき前提ノードを強調する
    CSS を段の数だけ生成する（依存関係ミニマップと同じ ``:has()`` 方式・JS なし）。
    ``node_html`` が付ける ``data-task`` 属性が対象。
    """

    blocks = "".join(
        f'<div class="qo-level"><div class="qo-levelnum">STEP {i}</div>'
        f'<div class="qo-nodes">{nodes}</div></div>'
        for i, nodes in enumerate(levels_html, start=1)
    )
    rules = ""
    if deps_by_task:
        rules = "".join(
            f'.qo-workflow:has(.qo-node[data-task="{esc(task_id)}"]:hover) '
            f'.qo-node[data-task="{esc(dep)}"]'
            "{outline:2px solid #cb932e;background:#fff3e0}"
            for task_id, deps in deps_by_task.items()
            for dep in deps
        )
    style = f"<style>{rules}</style>" if rules else ""
    return f'{style}<div class="qo-workflow">{blocks}</div>'


# ロジックツリー（依存関係）のカテゴリ別ノード塗り。qo-node の左罫色に合わせる。
_TREE_FILL: dict[str, str] = {"doc": "#e6f3f6", "code": "#edf0ff", "image": "#fff1e5"}
_TREE_BORDER: dict[str, str] = {"doc": "#087e8b", "code": "#5d68ac", "image": "#bb733c"}


def _dot_str(text: object, limit: int = 40) -> str:
    """DOT のラベル用エスケープ。長い文字列は丸める。"""

    s = str(text)
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def dependency_tree_dot(nodes: list[tuple[str, str, list[str], str]]) -> str:
    """依存関係をロジックツリー（上→下の有向グラフ）で描く DOT を返す。

    ``nodes`` は ``(task_id, title, dependency_ids, category)`` のリスト。
    ``st.graphviz_chart`` にそのまま渡す。前提 → タスク の向きで矢印を引く。
    """

    known = {task_id for task_id, _, _, _ in nodes}
    lines = [
        "digraph deps {",
        '  bgcolor="transparent";',
        "  rankdir=TB;",
        "  nodesep=0.35; ranksep=0.45;",
        '  node [shape=box, style="filled,rounded", fontname="Helvetica", '
        'fontsize=10, fontcolor="#1f2733", margin="0.14,0.09", penwidth=1.4];',
        '  edge [color="#9AA3B2", arrowsize=0.7, penwidth=1.1];',
    ]
    for task_id, title, _deps, category in nodes:
        fill = _TREE_FILL.get(category, "#eef1f4")
        border = _TREE_BORDER.get(category, "#8a92a0")
        label = f"{_dot_str(task_id, 8)}  {_dot_str(title)}"
        lines.append(
            f'  "{_dot_str(task_id, 8)}" [label="{label}", fillcolor="{fill}", color="{border}"];'
        )
    for task_id, _title, deps, _category in nodes:
        for dep in deps:
            if dep in known:
                lines.append(f'  "{_dot_str(dep, 8)}" -> "{_dot_str(task_id, 8)}";')
    lines.append("}")
    return "\n".join(lines)
