import { useRef, useState } from "react";
import * as XLSX from "xlsx";
import "./App.css";

// ── helpers ─────────────────────────────────────────────────────────────────

function _parseV(v) {
  if (v == null || v === "") return 0;
  const n = Number(v);
  return isNaN(n) ? 0 : n;
}

function _impostoLanc(l) {
  const d = (l.descricao_conta ?? "").toUpperCase();
  if (d.includes("PIS")) return "PIS";
  if (d.includes("COFINS")) return "COFINS";
  return "";
}

function _tipoLancamento(l) {
  return (l.descricao ?? "").startsWith("Estorno SAP")
    ? "estornoSap"
    : "ajuste";
}

function _sentido(l) {
  return l.debito != null ? "Débito" : "Crédito";
}

function fmt(val) {
  if (val == null || val === "") return "—";
  const n = Number(val);
  if (isNaN(n)) return "—";
  return n.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

// status do backend → _tipo de exibição
const STATUS_TIPO = {
  so_sped: "so_sped",
  so_sap: "so_sap",
  ok: "ok",
  complemento: "complemento",
  estorno: "estorno",
  apenas_sap: "so_sap",
  apenas_sped: "so_sped",
  sem_valor: "ok",
  advertencia: "advertencia",
};

const TIPO_BADGE = {
  divergencia: "g-badge--warn",
  complemento: "g-badge--warn",
  estorno: "g-badge--danger",
  so_sped: "g-badge--danger",
  so_sap: "g-badge--neutral",
  ok: "g-badge--success",
  advertencia: "g-badge--warn",
};
const TIPO_LABELS = {
  divergencia: "Divergência",
  complemento: "Complemento",
  estorno: "Estorno",
  so_sped: "Só SPED",
  so_sap: "Só SAP",
  ok: "OK",
  advertencia: "Aviso",
};

const IMPOSTOS_LANC = [
  { campo: "PIS", label: "PIS" },
  { campo: "COFINS", label: "COFINS" },
];

const TIPOS_LANC = [
  { key: "ajuste", label: "Ajuste", style: null },
  {
    key: "estornoSap",
    label: "Apenas SAP",
    style: { color: "var(--g-danger)" },
  },
];

const OPCOES_POR_PAGINA = [10, 20, 50, 100];

// ── exportação ───────────────────────────────────────────────────────────────

function exportarXLSX(lancamentos) {
  const dados = lancamentos.map((l) => ({
    "Código da Conta": l.codigo_da_conta ?? "",
    "Descrição da Conta": l.descricao_conta ?? "",
    Débito: l.debito ?? "",
    Crédito: l.credito ?? "",
    Descrição: l.descricao ?? "",
    "Centro de Custo": l.centro_de_custo ?? "",
    Filial: l.filial ?? "",
    Imposto: l._imposto ?? "",
    Sentido: _sentido(l),
  }));
  const ws = XLSX.utils.json_to_sheet(dados);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Lançamentos");
  XLSX.writeFile(wb, "lancamentos_ajuste.xlsx");
}

// ── componente principal ─────────────────────────────────────────────────────

export default function App() {
  const [sapFile, setSapFile] = useState(null);
  const [spedFile, setSpedFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState(null);
  const [resultado, setResultado] = useState(null);
  const [filtro, setFiltro] = useState("todos");
  const [abaAtiva, setAbaAtiva] = useState("comparacao");
  const [paginaComp, setPaginaComp] = useState(1);
  const [paginaLanc, setPaginaLanc] = useState(1);
  const [porPaginaComp, setPorPaginaComp] = useState(20);
  const [porPaginaLanc, setPorPaginaLanc] = useState(20);
  const [filtroTexto, setFiltroTexto] = useState("");
  const [filtroLanc, setFiltroLanc] = useState("");
  const [tiposLanc, setTiposLanc] = useState({
    ajuste: true,
    estornoSap: false,
  });
  const [impostosAtivos, setImpostosAtivos] = useState(() =>
    Object.fromEntries(IMPOSTOS_LANC.map((i) => [i.campo, true])),
  );
  const [blocosAtivos, setBlocosAtivos] = useState(null); // null = todos selecionados

  const sapRef = useRef(null);
  const spedRef = useRef(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!sapFile || !spedFile) return;

    setLoading(true);
    setErro(null);
    setResultado(null);
    setPaginaComp(1);
    setPaginaLanc(1);
    setFiltroTexto("");
    setFiltroLanc("");
    setTiposLanc({ ajuste: true, estornoSap: false });
    setBlocosAtivos(null);

    const form = new FormData();
    form.append("planilha_sap", sapFile);
    form.append("sped_contribuicoes", spedFile);

    try {
      const res = await fetch("/api/comparar/compara_planilha_sped", {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) setErro(data.detail ?? "Erro ao processar arquivos.");
      else setResultado(data);
    } catch {
      setErro("Falha na comunicação com o servidor.");
    } finally {
      setLoading(false);
    }
  }

  function mudarFiltro(val) {
    setFiltro(val);
    setPaginaComp(1);
  }

  // ── comparação ─────────────────────────────────────────────────────────────

  const todasLinhas = (resultado?.registros ?? []).map((r) => {
    const tipo = STATUS_TIPO[r.status] ?? "ok";
    const delta =
      tipo === "complemento" || tipo === "estorno"
        ? Math.round(Math.abs(_parseV(r.vl_sped) - _parseV(r.vl_sap)) * 100) /
          100
        : 0;
    return { ...r, _tipo: tipo, _delta: delta };
  });

  const _busca = filtroTexto.trim().toLowerCase();
  const linhasFiltradas = todasLinhas.filter((r) => {
    if (filtro === "divergencia") {
      if (r._tipo !== "complemento" && r._tipo !== "estorno") return false;
    } else if (filtro !== "todos" && r._tipo !== filtro) return false;
    if (!_busca) return true;
    return (
      String(r.num_doc ?? "")
        .toLowerCase()
        .includes(_busca) ||
      String(r.identificador ?? "")
        .toLowerCase()
        .includes(_busca) ||
      String(r.bloco ?? "")
        .toLowerCase()
        .includes(_busca) ||
      String(r.imposto ?? "")
        .toLowerCase()
        .includes(_busca)
    );
  });

  const totalPagsComp = Math.max(
    1,
    Math.ceil(linhasFiltradas.length / porPaginaComp),
  );
  const linhasPag = linhasFiltradas.slice(
    (paginaComp - 1) * porPaginaComp,
    paginaComp * porPaginaComp,
  );

  // ── lançamentos ────────────────────────────────────────────────────────────

  const blocosDisponiveis = resultado
    ? [
        ...new Set(
          (resultado.lancamentos ?? []).map((l) => l.bloco).filter(Boolean),
        ),
      ].sort()
    : [];

  const isBlocoAtivo = (bloco) =>
    blocosAtivos === null || blocosAtivos.includes(bloco);

  const _buscaLanc = filtroLanc.trim().toLowerCase();
  const lancamentos = (resultado?.lancamentos ?? [])
    .map((l) => ({
      ...l,
      _imposto: _impostoLanc(l),
      _tipoLanc: _tipoLancamento(l),
    }))
    .filter((l) => {
      if (!tiposLanc[l._tipoLanc]) return false;
      if (l._imposto && !impostosAtivos[l._imposto]) return false;
      if (!isBlocoAtivo(l.bloco)) return false;
      if (!_buscaLanc) return true;
      return (
        String(l.codigo_da_conta ?? "")
          .toLowerCase()
          .includes(_buscaLanc) ||
        String(l.descricao_conta ?? "")
          .toLowerCase()
          .includes(_buscaLanc) ||
        String(l.descricao ?? "")
          .toLowerCase()
          .includes(_buscaLanc) ||
        String(l.centro_de_custo ?? "")
          .toLowerCase()
          .includes(_buscaLanc)
      );
    });

  const totalPagsLanc = Math.max(
    1,
    Math.ceil(lancamentos.length / porPaginaLanc),
  );
  const lancPag = lancamentos.slice(
    (paginaLanc - 1) * porPaginaLanc,
    paginaLanc * porPaginaLanc,
  );

  function toggleImposto(campo) {
    setImpostosAtivos((prev) => ({ ...prev, [campo]: !prev[campo] }));
    setPaginaLanc(1);
  }
  function toggleTipoLanc(key) {
    setTiposLanc((prev) => ({ ...prev, [key]: !prev[key] }));
    setPaginaLanc(1);
  }
  function toggleBloco(bloco) {
    setBlocosAtivos((prev) => {
      const current = prev ?? blocosDisponiveis;
      return current.includes(bloco)
        ? current.filter((b) => b !== bloco)
        : [...current, bloco].sort();
    });
    setPaginaLanc(1);
  }
  function toggleTodosBlockos(todos) {
    setBlocosAtivos(todos ? null : []);
    setPaginaLanc(1);
  }

  // ── render ─────────────────────────────────────────────────────────────────

  return (
    <div>
      <nav className="g-navbar">
        <div className="g-navbar__brand">
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="12" y1="2" x2="12" y2="6" />
              <line x1="12" y1="18" x2="12" y2="22" />
              <line x1="2" y1="12" x2="6" y2="12" />
              <line x1="18" y1="12" x2="22" y2="12" />
              <line x1="4.9" y1="4.9" x2="7.7" y2="7.7" />
              <line x1="16.3" y1="16.3" x2="19.1" y2="19.1" />
              <line x1="4.9" y1="19.1" x2="7.7" y2="16.3" />
              <line x1="16.3" y1="7.7" x2="19.1" y2="4.9" />
              <line x1="12" y1="8" x2="12" y2="10" opacity=".6" />
              <line x1="12" y1="14" x2="12" y2="16" opacity=".6" />
              <line x1="8" y1="12" x2="10" y2="12" opacity=".6" />
              <line x1="14" y1="12" x2="16" y2="12" opacity=".6" />
            </g>
          </svg>
          Confronto SAP × SPED
        </div>
        <span className="g-helper g-hidden-sm">
          Comparação de lançamentos contábeis
        </span>
      </nav>

      <main
        className="g-container"
        style={{
          marginTop: "var(--g-space-8)",
          marginBottom: "var(--g-space-8)",
        }}
      >
        {/* ── Formulário ── */}
        <form
          className="g-section"
          onSubmit={handleSubmit}
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "var(--g-space-5)",
          }}
        >
          <h2 className="g-h2">Arquivos</h2>
          <div className="g-form-grid">
            <DropField
              label="Planilha SAP"
              required
              accept=".xlsx"
              file={sapFile}
              inputRef={sapRef}
              onChange={setSapFile}
              hint="Clique ou arraste o arquivo .xlsx"
            />
            <DropField
              label="SPED Contribuições"
              required
              accept=".txt"
              file={spedFile}
              inputRef={spedRef}
              onChange={setSpedFile}
              hint="Clique ou arraste o arquivo .txt"
            />
          </div>
          {erro && <div className="app-alert-err">{erro}</div>}
          <div className="g-form-actions">
            <button
              type="submit"
              className="g-btn g-btn--primary g-btn--lg"
              disabled={loading || !sapFile || !spedFile}
            >
              {loading ? "Processando..." : "Comparar"}
            </button>
          </div>
        </form>

        {/* ── Resultados ── */}
        {resultado && (
          <section
            className="g-section"
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "var(--g-space-5)",
            }}
          >
            {/* Cards de resumo */}
            <div className="g-grid g-grid--auto-160">
              <ResumoCard
                label="Divergências"
                valor={
                  todasLinhas.filter(
                    (r) => r._tipo === "complemento" || r._tipo === "estorno",
                  ).length
                }
                cor="warn"
              />
              <ResumoCard
                label="Só no SPED"
                valor={todasLinhas.filter((r) => r._tipo === "so_sped").length}
                cor="danger"
              />
              <ResumoCard
                label="Só no SAP"
                valor={todasLinhas.filter((r) => r._tipo === "so_sap").length}
                cor=""
              />
              <ResumoCard
                label="Lançamentos"
                valor={lancamentos.length}
                cor=""
              />
            </div>

            {/* Abas */}
            <div className="g-tabs">
              <button
                className={`g-tabs__item${abaAtiva === "comparacao" ? " g-tabs__item--active" : ""}`}
                onClick={() => setAbaAtiva("comparacao")}
              >
                Comparação
              </button>
              <button
                className={`g-tabs__item${abaAtiva === "lancamentos" ? " g-tabs__item--active" : ""}`}
                onClick={() => setAbaAtiva("lancamentos")}
              >
                Lançamentos
                {lancamentos.length > 0 && (
                  <span
                    className="g-badge g-badge--neutral"
                    style={{ marginLeft: 6 }}
                  >
                    {lancamentos.length}
                  </span>
                )}
              </button>
            </div>

            {/* ── Aba: Comparação ── */}
            {abaAtiva === "comparacao" && (
              <>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    flexWrap: "wrap",
                    gap: "var(--g-space-2)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "var(--g-space-1)",
                    }}
                  >
                    <div
                      className="g-cluster"
                      style={{ gap: "var(--g-space-1)" }}
                    >
                      {[
                        ["todos", "Todos"],
                        ["divergencia", "Divergências"],
                        ["ok", "OK"],
                      ].map(([val, label]) => (
                        <button
                          key={val}
                          className={`g-pill${filtro === val ? " g-pill--active" : ""}`}
                          onClick={() => mudarFiltro(val)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    {(filtro === "todos" ||
                      filtro === "so_sped" ||
                      filtro === "so_sap") && (
                      <div
                        className="g-cluster"
                        style={{
                          gap: "var(--g-space-1)",
                          paddingLeft: "var(--g-space-3)",
                        }}
                      >
                        <span className="g-helper" style={{ fontSize: 11 }}>
                          ↳
                        </span>
                        {[
                          ["so_sped", "Só SPED"],
                          ["so_sap", "Só SAP"],
                        ].map(([val, label]) => (
                          <button
                            key={val}
                            className={`g-pill${filtro === val ? " g-pill--active" : ""}`}
                            onClick={() => mudarFiltro(val)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    )}
                    {(filtro === "todos" ||
                      filtro === "divergencia" ||
                      filtro === "complemento" ||
                      filtro === "estorno") && (
                      <div
                        className="g-cluster"
                        style={{
                          gap: "var(--g-space-1)",
                          paddingLeft: "var(--g-space-3)",
                        }}
                      >
                        <span className="g-helper" style={{ fontSize: 11 }}>
                          ↳
                        </span>
                        {[
                          ["complemento", "Complemento"],
                          ["estorno", "Estorno"],
                        ].map(([val, label]) => (
                          <button
                            key={val}
                            className={`g-pill${filtro === val ? " g-pill--active" : ""}`}
                            onClick={() => mudarFiltro(val)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--g-space-2)",
                    }}
                  >
                    <input
                      className="g-input"
                      style={{ width: 260 }}
                      placeholder="Buscar por nota, chave, bloco ou imposto…"
                      value={filtroTexto}
                      onChange={(e) => {
                        setFiltroTexto(e.target.value);
                        setPaginaComp(1);
                      }}
                    />
                    {filtroTexto && (
                      <button
                        className="g-btn g-btn--sm"
                        onClick={() => {
                          setFiltroTexto("");
                          setPaginaComp(1);
                        }}
                        title="Limpar busca"
                      >
                        ×
                      </button>
                    )}
                    <span className="g-helper">
                      {linhasFiltradas.length} registro
                      {linhasFiltradas.length !== 1 ? "s" : ""}
                    </span>
                  </div>
                </div>

                <BarraPaginacao
                  pagina={paginaComp}
                  total={totalPagsComp}
                  porPagina={porPaginaComp}
                  totalItens={linhasFiltradas.length}
                  onPagina={setPaginaComp}
                  onPorPagina={(v) => {
                    setPorPaginaComp(v);
                    setPaginaComp(1);
                  }}
                />

                <div className="g-table-wrap">
                  <table className="g-table">
                    <thead>
                      <tr>
                        <th>Documento</th>
                        <th>Identificador</th>
                        <th>Bloco</th>
                        <th>Imposto</th>
                        <th>Tipo</th>
                        <th>Valor SPED</th>
                        <th>Valor SAP</th>
                        <th>Delta</th>
                      </tr>
                    </thead>
                    <tbody>
                      {linhasPag.length === 0 && (
                        <tr>
                          <td colSpan={8} className="g-empty">
                            Nenhum resultado.
                          </td>
                        </tr>
                      )}
                      {linhasPag.map((r, i) => (
                        <tr
                          key={i}
                          className={
                            r._tipo === "divergencia" ? "app-row-diff" : ""
                          }
                        >
                          <td>{r.num_doc || "—"}</td>
                          <td>
                            {r.identificador ? (
                              <code
                                className="g-mono"
                                style={{ fontSize: 11, whiteSpace: "nowrap" }}
                              >
                                {r.identificador}
                              </code>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td>
                            <span className="app-bloco">{r.bloco || "—"}</span>
                          </td>
                          <td>
                            <span className="g-badge g-badge--neutral">
                              {r.imposto}
                            </span>
                          </td>
                          <td>
                            <span className={`g-badge ${TIPO_BADGE[r._tipo]}`}>
                              {TIPO_LABELS[r._tipo]}
                            </span>
                          </td>
                          <td>
                            {r._tipo === "so_sap" || r._tipo === "advertencia"
                              ? "—"
                              : fmt(r.vl_sped)}
                          </td>
                          <td>{r._tipo === "so_sped" ? "—" : fmt(r.vl_sap)}</td>
                          <td className={r._delta > 0 ? "app-td-diff" : ""}>
                            {r._delta > 0 ? fmt(r._delta) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <BarraPaginacao
                  pagina={paginaComp}
                  total={totalPagsComp}
                  porPagina={porPaginaComp}
                  totalItens={linhasFiltradas.length}
                  onPagina={setPaginaComp}
                  onPorPagina={(v) => {
                    setPorPaginaComp(v);
                    setPaginaComp(1);
                  }}
                />
              </>
            )}

            {/* ── Aba: Lançamentos ── */}
            {abaAtiva === "lancamentos" && (
              <>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    flexWrap: "wrap",
                    gap: "var(--g-space-3)",
                  }}
                >
                  <div
                    style={{ display: "flex", flexDirection: "column", gap: 0 }}
                  >
                    <div
                      className="g-cluster"
                      style={{
                        gap: "var(--g-space-4)",
                        paddingBottom: "var(--g-space-2)",
                        borderBottom: "1px solid var(--g-border)",
                      }}
                    >
                      <span className="g-helper" style={{ fontSize: 11 }}>
                        Imposto:
                      </span>
                      {IMPOSTOS_LANC.map(({ campo, label }) => (
                        <label key={campo} className="g-check">
                          <input
                            type="checkbox"
                            checked={impostosAtivos[campo]}
                            onChange={() => toggleImposto(campo)}
                          />
                          {label}
                        </label>
                      ))}
                    </div>
                    <div
                      className="g-cluster"
                      style={{
                        gap: "var(--g-space-4)",
                        paddingTop: "var(--g-space-2)",
                      }}
                    >
                      <span className="g-helper" style={{ fontSize: 11 }}>
                        Tipo:
                      </span>
                      {TIPOS_LANC.map((t) => (
                        <label
                          key={t.key}
                          className="g-check"
                          style={t.style ?? undefined}
                        >
                          <input
                            type="checkbox"
                            checked={tiposLanc[t.key]}
                            onChange={() => toggleTipoLanc(t.key)}
                          />
                          {t.label}
                        </label>
                      ))}
                    </div>
                    {blocosDisponiveis.length > 0 && (
                      <div
                        className="g-cluster"
                        style={{
                          gap: "var(--g-space-3)",
                          paddingTop: "var(--g-space-2)",
                          borderTop: "1px solid var(--g-border)",
                          flexWrap: "wrap",
                        }}
                      >
                        <span className="g-helper" style={{ fontSize: 11 }}>
                          Bloco:
                        </span>
                        {blocosDisponiveis.map((bloco) => (
                          <label key={bloco} className="g-check">
                            <input
                              type="checkbox"
                              checked={isBlocoAtivo(bloco)}
                              onChange={() => toggleBloco(bloco)}
                            />
                            {bloco}
                          </label>
                        ))}
                        <button
                          className="g-btn g-btn--sm"
                          style={{ marginLeft: "var(--g-space-2)" }}
                          onClick={() =>
                            toggleTodosBlockos(blocosAtivos !== null)
                          }
                        >
                          {blocosAtivos === null
                            ? "Desmarcar todos"
                            : "Selecionar todos"}
                        </button>
                      </div>
                    )}
                  </div>
                  <div
                    className="g-cluster"
                    style={{ gap: "var(--g-space-2)" }}
                  >
                    <input
                      className="g-input"
                      style={{ width: 280 }}
                      placeholder="Buscar por conta, descrição ou C.Custo…"
                      value={filtroLanc}
                      onChange={(e) => {
                        setFiltroLanc(e.target.value);
                        setPaginaLanc(1);
                      }}
                    />
                    {filtroLanc && (
                      <button
                        className="g-btn g-btn--sm"
                        onClick={() => {
                          setFiltroLanc("");
                          setPaginaLanc(1);
                        }}
                        title="Limpar busca"
                      >
                        ×
                      </button>
                    )}
                    <span className="g-helper">
                      {lancamentos.length} lançamento
                      {lancamentos.length !== 1 ? "s" : ""}
                    </span>
                    <button
                      type="button"
                      className="g-btn g-btn--orange"
                      disabled={!lancamentos.length}
                      onClick={() => exportarXLSX(lancamentos)}
                    >
                      ↑ Exportar XLSX
                    </button>
                  </div>
                </div>

                {tiposLanc.estornoSap && (
                  <div className="app-alert-err">
                    <strong>Atenção — Apenas SAP:</strong> esses lançamentos
                    existem no SAP mas não constam no SPED. Verifique cada
                    documento antes de importar.
                  </div>
                )}

                {lancamentos.length === 0 ? (
                  <p className="g-empty">
                    Nenhum lançamento gerado — sem diferenças encontradas.
                  </p>
                ) : (
                  <>
                    <BarraPaginacao
                      pagina={paginaLanc}
                      total={totalPagsLanc}
                      porPagina={porPaginaLanc}
                      totalItens={lancamentos.length}
                      onPagina={setPaginaLanc}
                      onPorPagina={(v) => {
                        setPorPaginaLanc(v);
                        setPaginaLanc(1);
                      }}
                    />

                    <div className="g-table-wrap">
                      <table className="g-table">
                        <thead>
                          <tr>
                            <th>Código da Conta</th>
                            <th>Descrição da Conta</th>
                            <th>Débito</th>
                            <th>Crédito</th>
                            <th>Descrição</th>
                            <th>C.Custo</th>
                            <th>Filial</th>
                            <th>Imposto</th>
                            <th>Sentido</th>
                          </tr>
                        </thead>
                        <tbody>
                          {lancPag.map((l, i) => (
                            <tr
                              key={i}
                              className={
                                l._tipoLanc === "estornoSap"
                                  ? "app-row-estorno-sap"
                                  : ""
                              }
                            >
                              <td>
                                <code className="g-mono">
                                  {l.codigo_da_conta}
                                </code>
                              </td>
                              <td style={{ maxWidth: 200 }}>
                                <Trunc>{l.descricao_conta}</Trunc>
                              </td>
                              <td
                                className={
                                  l.debito != null ? "app-td-debito" : ""
                                }
                              >
                                {fmt(l.debito)}
                              </td>
                              <td
                                className={
                                  l.credito != null ? "app-td-credito" : ""
                                }
                              >
                                {fmt(l.credito)}
                              </td>
                              <td style={{ maxWidth: 240 }}>
                                <Trunc maxW={230}>{l.descricao}</Trunc>
                              </td>
                              <td>{l.centro_de_custo}</td>
                              <td>{l.filial}</td>
                              <td>
                                {l._imposto && (
                                  <span className="g-badge g-badge--neutral">
                                    {l._imposto}
                                  </span>
                                )}
                              </td>
                              <td className="g-helper">{_sentido(l)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    <BarraPaginacao
                      pagina={paginaLanc}
                      total={totalPagsLanc}
                      porPagina={porPaginaLanc}
                      totalItens={lancamentos.length}
                      onPagina={setPaginaLanc}
                      onPorPagina={(v) => {
                        setPorPaginaLanc(v);
                        setPaginaLanc(1);
                      }}
                    />
                  </>
                )}
              </>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

// ── sub-componentes ──────────────────────────────────────────────────────────

function BarraPaginacao({
  pagina,
  total,
  porPagina,
  totalItens,
  onPagina,
  onPorPagina,
}) {
  const inicio = totalItens === 0 ? 0 : (pagina - 1) * porPagina + 1;
  const fim = Math.min(pagina * porPagina, totalItens);

  const pages = [];
  for (let i = 1; i <= total; i++) {
    if (i === 1 || i === total || (i >= pagina - 2 && i <= pagina + 2)) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== "...") {
      pages.push("...");
    }
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: "var(--g-space-2)",
      }}
    >
      <div className="g-cluster" style={{ gap: "var(--g-space-2)" }}>
        <span className="g-helper">
          {inicio}–{fim} de {totalItens}
        </span>
        <select
          className="g-select"
          style={{ width: "auto", padding: "4px 8px" }}
          value={porPagina}
          onChange={(e) => onPorPagina(Number(e.target.value))}
        >
          {OPCOES_POR_PAGINA.map((n) => (
            <option key={n} value={n}>
              {n} por página
            </option>
          ))}
        </select>
      </div>
      {total > 1 && (
        <div className="g-cluster" style={{ gap: "var(--g-space-1)" }}>
          <button
            className="g-btn g-btn--sm"
            disabled={pagina === 1}
            onClick={() => onPagina(pagina - 1)}
          >
            ‹
          </button>
          {pages.map((p, i) =>
            p === "..." ? (
              <span
                key={`e${i}`}
                className="g-helper"
                style={{ padding: "0 4px" }}
              >
                …
              </span>
            ) : (
              <button
                key={p}
                className={`g-btn g-btn--sm${p === pagina ? " g-btn--primary" : ""}`}
                onClick={() => onPagina(p)}
              >
                {p}
              </button>
            ),
          )}
          <button
            className="g-btn g-btn--sm"
            disabled={pagina === total}
            onClick={() => onPagina(pagina + 1)}
          >
            ›
          </button>
        </div>
      )}
    </div>
  );
}

function DropField({
  label,
  required,
  accept,
  file,
  inputRef,
  onChange,
  hint,
}) {
  return (
    <div className="g-field">
      <label className="g-field__label">
        {label}{" "}
        {required && <span style={{ color: "var(--g-danger)" }}>*</span>}
      </label>
      <div
        className={`app-drop-zone${file ? " app-drop-zone--filled" : ""}`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          onChange(e.dataTransfer.files[0]);
        }}
        onClick={() => inputRef.current?.click()}
      >
        {file ? file.name : hint}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        hidden
        onChange={(e) => onChange(e.target.files[0])}
      />
    </div>
  );
}

function ResumoCard({ label, valor, cor }) {
  return (
    <div className={`g-stat-card${cor ? ` g-stat-card--${cor}` : ""}`}>
      <span className="g-stat-card__label">{label}</span>
      <span className="g-stat-card__value">{valor}</span>
    </div>
  );
}

function Trunc({ children, maxW = 220 }) {
  const text = typeof children === "string" ? children : undefined;
  return (
    <span
      title={text}
      style={{
        display: "block",
        maxWidth: maxW,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}
