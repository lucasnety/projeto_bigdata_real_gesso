/* =====================================================================
 * Real Gesso — front-end
 * Integração da interface com a API (api/main.py).
 *
 * Fluxo de cada operação:
 *   formulário -> validação no navegador -> fetch para a API ->
 *   tratamento da resposta (sucesso / erro por campo) -> atualiza a tela
 * ===================================================================== */

const API = "/api";

// ---------------------------------------------------------------------
// Utilitários
// ---------------------------------------------------------------------
const $ = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];

const moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const numero = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
const fmtMoeda = (v) => (v === null || v === undefined ? "—" : moeda.format(v));

function esc(v) {
  if (v === null || v === undefined || v === "") return '<span class="muted">—</span>';
  return String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Os dados brutos misturam AAAA-MM-DD e DD/MM/AAAA. Exibe sempre DD/MM/AAAA. */
function fmtData(v) {
  if (!v) return "—";
  const iso = paraISO(v);
  if (!iso) return esc(v);
  const [a, m, d] = iso.split("-");
  return `${d}/${m}/${a}`;
}
/** Converte qualquer um dos formatos para AAAA-MM-DD (usado nos campos de data). */
function paraISO(v) {
  if (!v) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(v);
  return m ? `${m[3]}-${m[2]}-${m[1]}` : "";
}
const hoje = () => new Date().toLocaleDateString("sv-SE"); // AAAA-MM-DD no fuso local

function debounce(fn, ms = 300) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ---------------------------------------------------------------------
// Cliente HTTP: toda chamada à API passa por aqui
// ---------------------------------------------------------------------
class ErroApi extends Error {
  constructor(status, corpo) {
    super(corpo?.detail || `Erro ${status}`);
    this.status = status;
    this.erros = corpo?.erros || {};
  }
}

async function api(metodo, caminho, corpo) {
  let resp;
  try {
    resp = await fetch(API + caminho, {
      method: metodo,
      headers: corpo ? { "Content-Type": "application/json" } : {},
      body: corpo ? JSON.stringify(corpo) : undefined,
    });
  } catch {
    marcarApi(false);
    throw new ErroApi(0, { detail: "Não foi possível conectar à API. Ela está rodando?" });
  }
  marcarApi(true);
  const dados = await resp.json().catch(() => null);
  if (!resp.ok) throw new ErroApi(resp.status, dados);
  return dados;
}

function marcarApi(ok) {
  const el = $("#status-api");
  el.className = "status-api " + (ok ? "on" : "off");
  el.textContent = ok ? "● API conectada" : "● API offline";
}

// ---------------------------------------------------------------------
// Avisos (toasts)
// ---------------------------------------------------------------------
function avisar(msg, tipo = "ok") {
  const el = document.createElement("div");
  el.className = "aviso " + (tipo === "erro" ? "erro" : "");
  el.textContent = msg;
  $("#avisos").append(el);
  setTimeout(() => el.remove(), tipo === "erro" ? 6000 : 3500);
}

function confirmar(texto) {
  const dlg = $("#confirmar");
  $("#confirmar-texto").textContent = texto;
  dlg.showModal();
  return new Promise((ok) => {
    dlg.onclick = (e) => {
      const r = e.target.dataset.resposta;
      if (r) { dlg.close(); ok(r === "sim"); }
    };
    dlg.oncancel = () => ok(false);
  });
}

// ---------------------------------------------------------------------
// Estado compartilhado (dados auxiliares vindos da API)
// ---------------------------------------------------------------------
const estado = {
  opcoes: null,         // GET /api/opcoes
  precos: [],           // GET /api/precos
  catalogo: [],         // precos + serviços sem preço oficial (para o select)
  clientes: null,       // lista resumida de clientes (para os selects)
  pagina: { clientes: 1, servicos: 1, manutencoes: 1 },
  destacar: null,       // id da linha recém-salva, para destacar na tabela
};

async function carregarClientesResumo(forcar = false) {
  if (estado.clientes && !forcar) return estado.clientes;
  const r = await api("GET", "/clientes?por_pagina=500");
  estado.clientes = r.itens
    .map((c) => ({ id: c.id_cliente, nome: c.nome_completo }))
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  return estado.clientes;
}

function preencherSelect(sel, valores, rotuloVazio) {
  sel.innerHTML = (rotuloVazio !== undefined ? `<option value="">${rotuloVazio}</option>` : "") +
    valores.map((v) => typeof v === "object"
      ? `<option value="${esc(v.valor)}">${esc(v.rotulo)}</option>`
      : `<option>${esc(v)}</option>`).join("");
}

function selo(status) {
  const s = (status || "").toLowerCase();
  const tipo = s.startsWith("conclu") ? "ok" : s === "cancelado" ? "perigo" : s === "orçado" || s === "solicitada" ? "neutro" : "alerta";
  return `<span class="selo ${tipo}">${esc(status)}</span>`;
}

function paginacao(el, r, aoMudar) {
  const paginas = Math.max(1, Math.ceil(r.total / r.por_pagina));
  el.innerHTML = `
    <span>${r.total} registro(s) · página ${r.pagina} de ${paginas}</span>
    <div>
      <button ${r.pagina <= 1 ? "disabled" : ""} data-p="${r.pagina - 1}">‹ Anterior</button>
      <button ${r.pagina >= paginas ? "disabled" : ""} data-p="${r.pagina + 1}">Próxima ›</button>
    </div>`;
  $$("button", el).forEach((b) => (b.onclick = () => aoMudar(+b.dataset.p)));
}

function linhaVazia(tbody, colunas, msg) {
  tbody.innerHTML = `<tr><td colspan="${colunas}" class="vazio">${msg}</td></tr>`;
}

// =====================================================================
// PAINEL
// =====================================================================
async function carregarPainel() {
  try {
    const r = await api("GET", "/resumo");
    const t = r.totais;
    $("#kpis").innerHTML = [
      ["Clientes", numero.format(t.clientes)],
      ["Serviços", numero.format(t.servicos)],
      ["Faturamento (concluídos)", moeda.format(t.faturamento)],
      ["Manutenções em aberto", numero.format(t.manutencoes_abertas)],
    ].map(([k, v]) => `<div class="cartao kpi"><span>${k}</span><strong>${v}</strong></div>`).join("");

    await desenharGraficoTipos(r);

    $("#tabela-status").innerHTML = `<thead><tr><th>Status</th><th class="num">Serviços</th><th class="num">%</th></tr></thead><tbody>` +
      r.por_status.map((s) => `<tr><td>${selo(s.status)}</td><td class="num">${s.quantidade}</td>
        <td class="num">${numero.format((s.quantidade / t.servicos) * 100)}%</td></tr>`).join("") + "</tbody>";
  } catch (e) {
    $("#kpis").innerHTML = `<div class="cartao vazio">${esc(e.message)}</div>`;
  }
}

/**
 * Gráfico "Serviços por tipo": a contagem vem do job Hadoop (MapReduce),
 * lido do HDFS pela API. O valor em R$ (dica do mouse) vem do Postgres.
 * Se o Hadoop estiver fora do ar, usa a contagem do Postgres e avisa.
 */
async function desenharGraficoTipos(resumo) {
  const aviso = $("#aviso-hadoop");
  const valorPorTipo = Object.fromEntries(resumo.por_tipo.map((x) => [x.tipo.toLowerCase(), x.valor]));
  let itens, legenda;
  aviso.hidden = true;

  try {
    const h = await api("GET", "/hadoop/servicos-por-tipo");
    itens = h.itens;
    const quando = new Date(h.gerado_em).toLocaleString("pt-BR");
    legenda = `Fonte: Hadoop MapReduce (${esc(h.fonte)}) · job de ${quando}`;
    if (h.total !== resumo.totais.servicos) {
      aviso.innerHTML = `Resultado do Hadoop desatualizado: ${h.total} serviços no Hadoop × ${resumo.totais.servicos} no banco. ` +
        `Rode o job de novo com <code>make hadoop</code>.`;
      aviso.hidden = false;
    }
  } catch (e) {
    itens = resumo.por_tipo;
    legenda = "Fonte: banco de dados (Postgres)";
    aviso.textContent = `Hadoop indisponível: ${e.message}`;
    aviso.hidden = false;
  }

  $("#sub-grafico").innerHTML = `${legenda} · passe o mouse para ver o valor`;
  const max = Math.max(...itens.map((x) => x.quantidade), 1);
  $("#grafico-tipos").innerHTML = `<div class="barras">${itens.map((x) => `
    <span class="rotulo">${esc(x.tipo)}</span>
    <div class="trilho" data-dica="${esc(x.tipo)}<br>${x.quantidade} serviços<br>${fmtMoeda(valorPorTipo[x.tipo.toLowerCase()])}">
      <div class="barra-v" style="width:${(x.quantidade / max) * 100}%"></div>
    </div>
    <span class="valor">${x.quantidade}</span>`).join("")}</div>`;
}

// Dica (tooltip) do gráfico
document.addEventListener("mousemove", (e) => {
  const alvo = e.target.closest("[data-dica]");
  const tip = $("#tooltip");
  if (!alvo) { tip.hidden = true; return; }
  tip.innerHTML = alvo.dataset.dica;
  tip.hidden = false;
  tip.style.left = Math.min(e.clientX + 12, innerWidth - tip.offsetWidth - 8) + "px";
  tip.style.top = e.clientY + 14 + "px";
});

// =====================================================================
// CLIENTES
// =====================================================================
async function carregarClientes(pagina = estado.pagina.clientes) {
  estado.pagina.clientes = pagina;
  const tbody = $("#lista-clientes");
  const p = new URLSearchParams({ pagina, por_pagina: 20 });
  if ($("#busca-clientes").value) p.set("busca", $("#busca-clientes").value);
  if ($("#filtro-cidade").value) p.set("cidade", $("#filtro-cidade").value);
  try {
    const r = await api("GET", "/clientes?" + p);
    if (!r.itens.length) linhaVazia(tbody, 8, "Nenhum cliente encontrado.");
    else tbody.innerHTML = r.itens.map((c) => `
      <tr data-id="${c.id_cliente}" class="${estado.destacar === "c" + c.id_cliente ? "novo" : ""}">
        <td class="muted">${c.id_cliente}</td><td>${esc(c.nome_completo)}</td><td>${esc(c.telefone)}</td>
        <td>${esc(c.email)}</td><td>${esc(c.cidade)}</td><td>${esc(c.origem_contato)}</td>
        <td class="num">${c.qtd_servicos}</td>
        <td><button class="link" data-editar>Editar</button><button class="link perigo" data-excluir>Excluir</button></td>
      </tr>`).join("");
    paginacao($("#pag-clientes"), r, carregarClientes);
  } catch (e) { linhaVazia(tbody, 8, esc(e.message)); }
}

const FORM_CLIENTE = {
  recurso: "clientes", id: "id_cliente", titulo: "cliente",
  campos: () => [
    { nome: "nome_completo", rotulo: "Nome completo", obrig: true, largo: true, attrs: 'maxlength="150" autocomplete="off"' },
    { nome: "telefone", rotulo: "Telefone", ajuda: "Com DDD. Ex.: (19) 99999-9999", attrs: 'inputmode="tel"' },
    { nome: "email", rotulo: "E-mail", tipo: "email", attrs: 'maxlength="100"' },
    { nome: "endereco", rotulo: "Endereço", largo: true, attrs: 'maxlength="200"' },
    { nome: "cidade", rotulo: "Cidade", tipo: "select", opcoes: estado.opcoes.cidades, vazio: "Selecione…" },
    { nome: "origem_contato", rotulo: "Como conheceu a empresa", tipo: "select", opcoes: estado.opcoes.origens, vazio: "Selecione…" },
  ],
  validar(d) {
    const e = {};
    if (!d.nome_completo) e.nome_completo = "Informe o nome do cliente.";
    else if (d.nome_completo.trim().split(/\s+/).length < 2) e.nome_completo = "Informe nome e sobrenome.";
    if (d.telefone) {
      let dig = d.telefone.replace(/\D/g, "");
      if (dig.startsWith("55") && dig.length >= 12) dig = dig.slice(2);
      if (dig.length < 10 || dig.length > 11) e.telefone = "Telefone inválido. Use DDD + número.";
    }
    if (d.email && !/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(d.email)) e.email = "E-mail inválido.";
    if (!d.telefone && !d.email) e.telefone = e.email = "Informe telefone ou e-mail.";
    return e;
  },
  aoSalvar: () => { carregarClientesResumo(true); carregarClientes(1); },
};

// =====================================================================
// SERVIÇOS
// =====================================================================
async function carregarServicos(pagina = estado.pagina.servicos) {
  estado.pagina.servicos = pagina;
  const tbody = $("#lista-servicos");
  const p = new URLSearchParams({ pagina, por_pagina: 20 });
  if ($("#busca-servicos").value) p.set("busca", $("#busca-servicos").value);
  if ($("#filtro-tipo").value) p.set("tipo", $("#filtro-tipo").value);
  if ($("#filtro-status-servico").value) p.set("status", $("#filtro-status-servico").value);
  try {
    const r = await api("GET", "/servicos?" + p);
    if (!r.itens.length) linhaVazia(tbody, 9, "Nenhum serviço encontrado.");
    else tbody.innerHTML = r.itens.map((s) => `
      <tr data-id="${s.id_servico}" class="${estado.destacar === "s" + s.id_servico ? "novo" : ""}">
        <td class="muted">${s.id_servico}</td><td>${esc(s.cliente)}</td>
        <td>${esc(s.tipo_servico)}${s.subtipo ? ` <span class="muted">· ${esc(s.subtipo)}</span>` : ""}</td>
        <td class="num">${s.quantidade !== null ? numero.format(s.quantidade) : "—"} <span class="muted">${s.unidade_medida?.includes("quadrado") || s.unidade_medida === "m2" ? "m²" : "m"}</span></td>
        <td class="num">${s.valor_unitario_aplicado !== null ? fmtMoeda(s.valor_unitario_aplicado) : '<span class="muted">a combinar</span>'}</td>
        <td class="num">${fmtMoeda(s.valor_total)}</td>
        <td>${fmtData(s.data_execucao)}</td><td>${selo(s.status_padronizado)}</td>
        <td><button class="link" data-editar>Editar</button><button class="link perigo" data-excluir>Excluir</button></td>
      </tr>`).join("");
    paginacao($("#pag-servicos"), r, carregarServicos);
  } catch (e) { linhaVazia(tbody, 9, esc(e.message)); }
}

/** Índice do catálogo (tipo + subtipo) que corresponde a um serviço existente. */
function indiceCatalogo(tipo, subtipo) {
  return estado.catalogo.findIndex((c) =>
    c.tipo_servico.toLowerCase() === (tipo || "").toLowerCase() && (c.subtipo || "") === (subtipo || ""));
}

const FORM_SERVICO = {
  recurso: "servicos", id: "id_servico", titulo: "serviço",
  campos: () => [
    { nome: "id_cliente", rotulo: "Cliente", tipo: "select", obrig: true, largo: true, vazio: "Selecione o cliente…",
      opcoes: estado.clientes.map((c) => ({ valor: c.id, rotulo: `${c.nome} (#${c.id})` })) },
    { nome: "catalogo", rotulo: "Serviço", tipo: "select", obrig: true, vazio: "Selecione…",
      opcoes: estado.catalogo.map((c, i) => ({ valor: i, rotulo: c.subtipo ? `${c.tipo_servico} — ${c.subtipo}` : c.tipo_servico })) },
    { nome: "unidade_medida", rotulo: "Unidade", tipo: "select", obrig: true, opcoes: estado.opcoes.unidades },
    { nome: "quantidade", rotulo: "Quantidade", tipo: "number", obrig: true, attrs: 'min="0.01" step="0.01"' },
    { nome: "valor_unitario_aplicado", rotulo: "Valor unitário (R$)", tipo: "number", attrs: 'min="0.01" step="0.01"',
      ajuda: "Vazio = preço da tabela oficial" },
    { nome: "data_execucao", rotulo: "Data de execução", tipo: "date", obrig: true },
    { nome: "status", rotulo: "Status", tipo: "select", obrig: true, opcoes: estado.opcoes.status_servico },
    { nome: "descricao_detalhada", rotulo: "Descrição", tipo: "textarea", largo: true },
    { html: '<div class="total-previa" id="total-previa"></div>' },
  ],
  /** Converte um registro da API para os valores dos campos. */
  paraForm(s) {
    const unidade = { m2: "metro quadrado", "m linear": "metro linear" }[s.unidade_medida] || s.unidade_medida;
    return { ...s, catalogo: indiceCatalogo(s.tipo_servico, s.subtipo), unidade_medida: unidade,
      data_execucao: paraISO(s.data_execucao), status: s.status_padronizado };
  },
  /** Converte os campos do formulário para o corpo enviado à API. */
  paraApi(d) {
    const item = estado.catalogo[d.catalogo] || {};
    return {
      id_cliente: d.id_cliente ? Number(d.id_cliente) : null,
      tipo_servico: item.tipo_servico || null, subtipo: item.subtipo || "",
      unidade_medida: d.unidade_medida, quantidade: d.quantidade === "" ? null : Number(d.quantidade),
      valor_unitario_aplicado: d.valor_unitario_aplicado === "" ? null : Number(d.valor_unitario_aplicado),
      data_execucao: d.data_execucao, status: d.status, descricao_detalhada: d.descricao_detalhada,
    };
  },
  validar(d) {
    const e = {};
    if (!d.id_cliente) e.id_cliente = "Selecione o cliente.";
    if (d.catalogo === "") e.catalogo = "Selecione o serviço.";
    const item = estado.catalogo[d.catalogo];
    if (d.quantidade === "" || Number(d.quantidade) <= 0) e.quantidade = "A quantidade deve ser maior que zero.";
    if (d.valor_unitario_aplicado !== "" && Number(d.valor_unitario_aplicado) <= 0) e.valor_unitario_aplicado = "O valor deve ser maior que zero.";
    if (item && item.valor === null && d.valor_unitario_aplicado === "") e.valor_unitario_aplicado = "Sem preço oficial: informe o valor.";
    if (!d.data_execucao) e.data_execucao = "Informe a data de execução.";
    return e;
  },
  /** Comportamento dinâmico: preço sugerido e prévia do total. */
  aoAbrir(form) {
    const cat = form.elements.catalogo, un = form.elements.unidade_medida;
    const qtd = form.elements.quantidade, val = form.elements.valor_unitario_aplicado;
    const atualizar = () => {
      const item = estado.catalogo[cat.value];
      val.placeholder = item?.valor ? `${numero.format(item.valor)} (tabela)` : item ? "obrigatório" : "";
      const unit = val.value !== "" ? Number(val.value) : item?.valor;
      const total = Number(qtd.value) > 0 && unit ? Number(qtd.value) * unit : null;
      $("#total-previa").innerHTML = total
        ? `Total estimado: <strong>${moeda.format(total)}</strong> <span class="muted">(${numero.format(qtd.value)} × ${moeda.format(unit)})</span>`
        : '<span class="muted">Preencha serviço e quantidade para ver o total.</span>';
    };
    cat.addEventListener("change", () => {
      const item = estado.catalogo[cat.value];
      if (item) un.value = item.unidade_medida; // a unidade vem da tabela de preços
      atualizar();
    });
    [qtd, val].forEach((el) => el.addEventListener("input", atualizar));
    atualizar();
  },
  novo: () => ({ data_execucao: hoje(), status: "orçado" }),
  aoSalvar: () => carregarServicos(1),
};

// =====================================================================
// MANUTENÇÕES
// =====================================================================
async function carregarManutencoes(pagina = estado.pagina.manutencoes) {
  estado.pagina.manutencoes = pagina;
  const tbody = $("#lista-manutencoes");
  const p = new URLSearchParams({ pagina, por_pagina: 20 });
  if ($("#busca-manutencoes").value) p.set("busca", $("#busca-manutencoes").value);
  if ($("#filtro-status-manutencao").value) p.set("status", $("#filtro-status-manutencao").value);
  try {
    const r = await api("GET", "/manutencoes?" + p);
    if (!r.itens.length) linhaVazia(tbody, 9, "Nenhuma manutenção encontrada.");
    else tbody.innerHTML = r.itens.map((m) => `
      <tr data-id="${m.id_manutencao}" class="${estado.destacar === "m" + m.id_manutencao ? "novo" : ""}">
        <td class="muted">${m.id_manutencao}</td><td>${esc(m.cliente)}</td><td class="quebra">${esc(m.descricao)}</td>
        <td>${m.id_servico_origem ? `#${m.id_servico_origem} ${esc(m.servico_origem)}` : '<span class="muted">sem vínculo</span>'}</td>
        <td class="num">${m.preco !== null ? fmtMoeda(m.preco) : '<span class="muted">garantia</span>'}</td>
        <td>${fmtData(m.data_solicitacao)}</td><td>${fmtData(m.data_execucao)}</td><td>${selo(m.status)}</td>
        <td><button class="link" data-editar>Editar</button><button class="link perigo" data-excluir>Excluir</button></td>
      </tr>`).join("");
    paginacao($("#pag-manutencoes"), r, carregarManutencoes);
  } catch (e) { linhaVazia(tbody, 9, esc(e.message)); }
}

const FORM_MANUTENCAO = {
  recurso: "manutencoes", id: "id_manutencao", titulo: "manutenção",
  campos: () => [
    { nome: "id_cliente", rotulo: "Cliente", tipo: "select", obrig: true, largo: true, vazio: "Selecione o cliente…",
      opcoes: estado.clientes.map((c) => ({ valor: c.id, rotulo: `${c.nome} (#${c.id})` })) },
    { nome: "id_servico_origem", rotulo: "Serviço de origem", tipo: "select", largo: true, vazio: "Selecione o cliente primeiro", opcoes: [],
      ajuda: "Serviços do cliente selecionado (carregados da API)" },
    { nome: "descricao", rotulo: "Problema relatado", tipo: "textarea", obrig: true, largo: true },
    { nome: "preco", rotulo: "Preço (R$)", tipo: "number", attrs: 'min="0" step="0.01"', ajuda: "Vazio = garantia / a combinar" },
    { nome: "status", rotulo: "Status", tipo: "select", obrig: true, opcoes: estado.opcoes.status_manutencao },
    { nome: "data_solicitacao", rotulo: "Data da solicitação", tipo: "date", obrig: true },
    { nome: "data_execucao", rotulo: "Data de execução", tipo: "date", ajuda: "Obrigatória se concluída" },
  ],
  paraForm: (m) => ({ ...m, data_solicitacao: paraISO(m.data_solicitacao), data_execucao: paraISO(m.data_execucao) }),
  paraApi: (d) => ({
    id_cliente: d.id_cliente ? Number(d.id_cliente) : null,
    id_servico_origem: d.id_servico_origem ? Number(d.id_servico_origem) : null,
    descricao: d.descricao, preco: d.preco === "" ? null : Number(d.preco),
    data_solicitacao: d.data_solicitacao, data_execucao: d.data_execucao || null, status: d.status,
  }),
  validar(d) {
    const e = {};
    if (!d.id_cliente) e.id_cliente = "Selecione o cliente.";
    if (!d.descricao || d.descricao.trim().length < 5) e.descricao = "Descreva o problema (mínimo 5 caracteres).";
    if (d.preco !== "" && Number(d.preco) < 0) e.preco = "O preço não pode ser negativo.";
    if (!d.data_solicitacao) e.data_solicitacao = "Informe a data da solicitação.";
    if (d.data_execucao && d.data_solicitacao && d.data_execucao < d.data_solicitacao) e.data_execucao = "Não pode ser antes da solicitação.";
    if (d.status === "concluída" && !d.data_execucao) e.data_execucao = "Informe a data de execução.";
    return e;
  },
  /** Ao trocar o cliente, busca na API os serviços dele. */
  aoAbrir(form, registro) {
    const cli = form.elements.id_cliente, sel = form.elements.id_servico_origem;
    const carregar = async (manter) => {
      if (!cli.value) { preencherSelect(sel, [], "Selecione o cliente primeiro"); return; }
      preencherSelect(sel, [], "Carregando…");
      try {
        const r = await api("GET", `/servicos?id_cliente=${cli.value}&por_pagina=200`);
        preencherSelect(sel, r.itens.map((s) => ({ valor: s.id_servico,
          rotulo: `#${s.id_servico} · ${s.tipo_servico} · ${fmtData(s.data_execucao)}` })),
          r.itens.length ? "Sem vínculo" : "Cliente sem serviços");
        if (manter) sel.value = manter;
      } catch (e) { preencherSelect(sel, [], "Erro ao carregar serviços"); }
    };
    cli.addEventListener("change", () => carregar());
    carregar(registro?.id_servico_origem);
  },
  novo: () => ({ data_solicitacao: hoje(), status: "solicitada" }),
  aoSalvar: () => carregarManutencoes(1),
};

// =====================================================================
// PREÇOS
// =====================================================================
async function carregarPrecos() {
  $("#lista-precos").innerHTML = estado.precos.map((p) => `
    <tr><td>${esc(p.tipo_servico)}</td><td>${esc(p.subtipo)}</td><td>${esc(p.unidade_medida)}</td>
    <td class="num">${fmtMoeda(p.valor)}</td></tr>`).join("");
}

// =====================================================================
// Motor genérico de formulário (cria, edita, valida e envia)
// =====================================================================
const FORMS = { clientes: FORM_CLIENTE, servicos: FORM_SERVICO, manutencoes: FORM_MANUTENCAO };
let formAtual = null;

function renderCampo(c) {
  if (c.html) return c.html;
  const obrig = c.obrig ? ' <span class="obrig">*</span>' : "";
  let entrada;
  if (c.tipo === "select") {
    const ops = c.opcoes.map((o) => typeof o === "object"
      ? `<option value="${esc(o.valor)}">${esc(o.rotulo)}</option>` : `<option>${esc(o)}</option>`).join("");
    entrada = `<select id="f-${c.nome}" name="${c.nome}">${c.vazio !== undefined ? `<option value="">${c.vazio}</option>` : ""}${ops}</select>`;
  } else if (c.tipo === "textarea") {
    entrada = `<textarea id="f-${c.nome}" name="${c.nome}" rows="3"></textarea>`;
  } else {
    entrada = `<input id="f-${c.nome}" name="${c.nome}" type="${c.tipo || "text"}" ${c.attrs || ""}>`;
  }
  return `<div class="campo ${c.largo ? "largo" : ""}" data-campo="${c.nome}">
    <label for="f-${c.nome}">${c.rotulo}${obrig}</label>${entrada}
    ${c.ajuda ? `<span class="ajuda">${c.ajuda}</span>` : ""}<span class="erro"></span></div>`;
}

async function abrirForm(recurso, registro = null) {
  const cfg = FORMS[recurso];
  if (recurso !== "clientes") await carregarClientesResumo();
  formAtual = { cfg, registro };
  const form = $("#form");
  $("#form-titulo").textContent = registro ? `Editar ${cfg.titulo} #${registro[cfg.id]}` : `Novo ${cfg.titulo}`.replace("Novo manutenção", "Nova manutenção");
  $("#form-campos").innerHTML = cfg.campos().map(renderCampo).join("");
  limparErros();

  const valores = registro ? (cfg.paraForm ? cfg.paraForm(registro) : registro) : (cfg.novo ? cfg.novo() : {});
  for (const el of form.elements) {
    if (el.name && valores[el.name] !== undefined && valores[el.name] !== null) el.value = valores[el.name];
  }
  cfg.aoAbrir?.(form, registro);
  // Ao corrigir um campo, o erro dele some
  form.oninput = (e) => e.target.name && mostrarErro(e.target.name, "");
  $("#modal").showModal();
  form.elements[0]?.focus();
}

function lerForm() {
  const d = {};
  for (const el of $("#form").elements) if (el.name) d[el.name] = el.value.trim();
  return d;
}

function mostrarErro(campo, msg) {
  const box = $(`[data-campo="${campo}"]`);
  if (!box) return false;
  box.classList.toggle("invalido", !!msg);
  $(".erro", box).textContent = msg || "";
  return true;
}

function limparErros() {
  $$(".campo").forEach((c) => { c.classList.remove("invalido"); $(".erro", c).textContent = ""; });
  $("#erro-geral").hidden = true;
}

/** Campos da API que aparecem com outro nome no formulário. */
const MAPA_CAMPOS = { tipo_servico: "catalogo", subtipo: "catalogo" };

$("#form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const { cfg, registro } = formAtual;
  limparErros();

  // 1) validação no navegador (resposta imediata ao usuário)
  const dados = lerForm();
  const erros = cfg.validar(dados);
  if (Object.keys(erros).length) {
    Object.entries(erros).forEach(([c, m]) => mostrarErro(c, m));
    $(".campo.invalido input, .campo.invalido select, .campo.invalido textarea")?.focus();
    return;
  }

  // 2) envio para a API
  const botao = $("#form-salvar");
  botao.disabled = true; botao.textContent = "Salvando…";
  try {
    const corpo = cfg.paraApi ? cfg.paraApi(dados) : dados;
    const salvo = registro
      ? await api("PUT", `/${cfg.recurso}/${registro[cfg.id]}`, corpo)
      : await api("POST", `/${cfg.recurso}`, corpo);

    // 3) sucesso: fecha, avisa e atualiza a interface
    $("#modal").close();
    estado.destacar = cfg.recurso[0] + salvo[cfg.id];
    avisar(registro ? `${cap(cfg.titulo)} #${salvo[cfg.id]} atualizado(a).` : `${cap(cfg.titulo)} #${salvo[cfg.id]} cadastrado(a).`);
    cfg.aoSalvar();
    carregarPainel();
  } catch (e) {
    // 4) erro: a API devolve {detail, erros:{campo: mensagem}}
    let algumCampo = false;
    for (const [campo, msg] of Object.entries(e.erros || {})) {
      algumCampo = mostrarErro(MAPA_CAMPOS[campo] || campo, msg) || algumCampo;
    }
    const geral = e.erros?.geral || (!algumCampo || e.status === 0 ? e.message : "");
    if (geral) { $("#erro-geral").textContent = geral; $("#erro-geral").hidden = false; }
  } finally {
    botao.disabled = false; botao.textContent = "Salvar";
  }
});

const cap = (s) => s[0].toUpperCase() + s.slice(1);

// Botões "Editar" / "Excluir" nas tabelas (delegação de eventos)
for (const recurso of Object.keys(FORMS)) {
  $(`#lista-${recurso}`).addEventListener("click", async (ev) => {
    const linha = ev.target.closest("tr[data-id]");
    if (!linha) return;
    const cfg = FORMS[recurso], id = linha.dataset.id;

    if (ev.target.matches("[data-editar]")) {
      try { abrirForm(recurso, await api("GET", `/${recurso}/${id}`)); }
      catch (e) { avisar(e.message, "erro"); }
    }
    if (ev.target.matches("[data-excluir]")) {
      if (!(await confirmar(`Excluir ${cfg.titulo} #${id}? Esta ação não pode ser desfeita.`))) return;
      try {
        const r = await api("DELETE", `/${recurso}/${id}`);
        avisar(r.detail);
        if (recurso === "clientes") carregarClientesResumo(true);
        cfg.aoSalvar();
        carregarPainel();
      } catch (e) { avisar(e.message, "erro"); } // ex.: 409 cliente com serviços
    }
  });
}

$$("[data-novo]").forEach((b) => b.addEventListener("click", () => abrirForm(b.dataset.novo)));
$$("[data-fechar]").forEach((b) => b.addEventListener("click", () => $("#modal").close()));

// =====================================================================
// Abas, filtros e inicialização
// =====================================================================
const CARREGAR = {
  painel: carregarPainel, clientes: () => carregarClientes(),
  servicos: () => carregarServicos(), manutencoes: () => carregarManutencoes(), precos: carregarPrecos,
};

function trocarAba(nome) {
  $$(".abas button").forEach((b) => b.setAttribute("aria-selected", b.dataset.aba === nome));
  $$(".aba").forEach((s) => s.classList.toggle("ativa", s.id === "aba-" + nome));
  history.replaceState(null, "", "#" + nome);
  CARREGAR[nome]();
}
$$(".abas button").forEach((b) => b.addEventListener("click", () => trocarAba(b.dataset.aba)));

$("#busca-clientes").addEventListener("input", debounce(() => carregarClientes(1)));
$("#filtro-cidade").addEventListener("change", () => carregarClientes(1));
$("#busca-servicos").addEventListener("input", debounce(() => carregarServicos(1)));
$("#filtro-tipo").addEventListener("change", () => carregarServicos(1));
$("#filtro-status-servico").addEventListener("change", () => carregarServicos(1));
$("#busca-manutencoes").addEventListener("input", debounce(() => carregarManutencoes(1)));
$("#filtro-status-manutencao").addEventListener("change", () => carregarManutencoes(1));

async function iniciar() {
  try {
    [estado.opcoes, estado.precos] = await Promise.all([api("GET", "/opcoes"), api("GET", "/precos")]);
  } catch (e) {
    avisar(e.message, "erro");
    $("#kpis").innerHTML = `<div class="cartao vazio">${esc(e.message)}</div>`;
    return;
  }
  estado.catalogo = [
    ...estado.precos.map((p) => ({ tipo_servico: p.tipo_servico, subtipo: p.subtipo || "", unidade_medida: p.unidade_medida, valor: p.valor })),
    ...estado.opcoes.tipos_sem_preco_oficial.map((t) => ({ ...t, valor: null })),
  ];
  preencherSelect($("#filtro-cidade"), estado.opcoes.cidades, "Todas as cidades");
  preencherSelect($("#filtro-tipo"), [...new Set(estado.catalogo.map((c) => c.tipo_servico))], "Todos os tipos");
  preencherSelect($("#filtro-status-servico"), estado.opcoes.status_servico, "Todos os status");
  preencherSelect($("#filtro-status-manutencao"), estado.opcoes.status_manutencao, "Todos os status");

  const inicial = location.hash.slice(1);
  trocarAba(CARREGAR[inicial] ? inicial : "painel");
}

iniciar();
