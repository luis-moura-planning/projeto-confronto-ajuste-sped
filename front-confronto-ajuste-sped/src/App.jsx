import { useRef, useState } from "react";
import * as XLSX from "xlsx";
import "./App.css";

const TOLERANCIA = 0.05;

function _reclas(r) {
  const vlPis    = r.VL_PIS    ?? r.VL_PIS_D    ?? r.VL_PIS_C5    ?? 0;
  const vlCofins = r.VL_COFINS ?? r.VL_COFINS_D ?? r.VL_COFINS_C5 ?? 0;
  const deltaPis    = vlPis    - (r.VL_PIS_SAP    ?? 0);
  const deltaCofins = vlCofins - (r.VL_COFINS_SAP ?? 0);
  const tipo = Math.abs(deltaPis) > TOLERANCIA || Math.abs(deltaCofins) > TOLERANCIA
    ? "divergencia"
    : "ok";
  return {
    ...r,
    VL_PIS:       vlPis,
    VL_COFINS:    vlCofins,
    _tipo:        tipo,
    DELTA_PIS:    Math.round(deltaPis    * 100) / 100,
    DELTA_COFINS: Math.round(deltaCofins * 100) / 100,
  };
}

const TAXAS = ["VL_PIS", "VL_COFINS"];
const TAXA_LABELS = {
  VL_PIS: "PIS",
  VL_COFINS: "COFINS",
};

const IMPOSTOS_LANC = [
  { campo: "PIS", label: "PIS" },
  { campo: "COFINS", label: "COFINS" },
];

const TIPO_BADGE = {
  divergencia: "g-badge--warn",
  so_sped: "g-badge--danger",
  so_sap: "g-badge--neutral",
  ok: "g-badge--success",
};
const TIPO_LABELS = {
  divergencia: "Divergência",
  so_sped: "Só SPED",
  so_sap: "Só SAP",
  ok: "OK",
};

function _bloco(r) {
  if (r.COD_CTA != null) return "F100";
  if (r.CHV_CTE != null) return "D";
  if (r._c500 || r.VL_PIS_C5 != null || r.VL_COFINS_C5 != null) return "C500";
  return "C";
}

const BLOCO_CLASS = { C: "app-bloco--c", D: "app-bloco--d", F100: "app-bloco--f100", C500: "app-bloco--c500" };
const BLOCO_LABEL = { C: "Bloco C", D: "Bloco D", F100: "F100", C500: "C500" };

const OPCOES_POR_PAGINA = [10, 20, 50, 100];

function fmt(val) {
  if (val == null) return "—";
  const n = Number(val);
  if (isNaN(n)) return "—";
  return n.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function exportarXLSX(lancamentos) {
  const cols = [
    "Código da Conta",
    "Descrição da Conta",
    "Débito",
    "Crédito",
    "Descrição",
    "Centro de Custo",
    "Filial",
    "Imposto",
    "Sentido",
  ];
  const dados = lancamentos.map((l) =>
    Object.fromEntries(cols.map((k) => [k, l[k] ?? ""])),
  );
  const ws = XLSX.utils.json_to_sheet(dados);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Lançamentos");
  XLSX.writeFile(wb, "lancamentos_ajuste.xlsx");
}

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
  const [impostosAtivos, setImpostosAtivos] = useState(() =>
    Object.fromEntries(IMPOSTOS_LANC.map((i) => [i.campo, true])),
  );
  const [filtroTexto, setFiltroTexto] = useState("");
  const [filtroLanc, setFiltroLanc] = useState("");
  const [incluirSoSped, setIncluirSoSped] = useState(false);

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
    setPorPaginaComp(20);
    setPorPaginaLanc(20);
    setFiltroTexto("");
    setFiltroLanc("");

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

  const todasLinhas = resultado
    ? [
        // Reclassifica divergencias e ok do backend usando apenas PIS e COFINS
        ...[...(resultado.divergencias ?? []), ...(resultado.ok ?? [])].map(_reclas),
        // Só SPED: mantém registros com PIS ou COFINS (incluindo variantes _D e _C5)
        ...(resultado.so_sped ?? [])
          .filter((r) => (r.VL_PIS ?? r.VL_PIS_D ?? r.VL_PIS_C5 ?? 0) !== 0 || (r.VL_COFINS ?? r.VL_COFINS_D ?? r.VL_COFINS_C5 ?? 0) !== 0)
          .map((r) => ({
            ...r,
            VL_PIS:    r.VL_PIS    ?? r.VL_PIS_D    ?? r.VL_PIS_C5    ?? 0,
            VL_COFINS: r.VL_COFINS ?? r.VL_COFINS_D ?? r.VL_COFINS_C5 ?? 0,
            _tipo: "so_sped",
          })),
        // Só SAP: mantém apenas registros com PIS ou COFINS
        ...(resultado.so_sap ?? [])
          .filter((r) => (r.VL_PIS_SAP ?? 0) !== 0 || (r.VL_COFINS_SAP ?? 0) !== 0)
          .map((r) => ({ ...r, _tipo: "so_sap" })),
      ]
    : [];

  const _busca = filtroTexto.trim().toLowerCase();
  const linhasFiltradas = todasLinhas.filter((r) => {
    if (filtro !== "todos" && r._tipo !== filtro) return false;
    if (!_busca) return true;
    return (
      String(r.NUM_DOC   ?? "").toLowerCase().includes(_busca) ||
      String(r.CHV_NFE   ?? r.CHV_CTE ?? "").toLowerCase().includes(_busca) ||
      String(r.COD_CTA   ?? "").toLowerCase().includes(_busca) ||
      String(r.NOME_CONTA ?? "").toLowerCase().includes(_busca) ||
      BLOCO_LABEL[_bloco(r)].toLowerCase().includes(_busca)
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

  const lancSoSped = incluirSoSped
    ? (resultado?.lancamentos_so_sped ?? []).map((l) => ({ ...l, _soSped: true }))
    : [];

  const _buscaLanc = filtroLanc.trim().toLowerCase();
  const lancamentos = [...(resultado?.lancamentos ?? []), ...lancSoSped].filter((l) => {
    const impostoKey = (l["Imposto"] ?? "").replace(/_D$/, "");
    if (impostosAtivos[impostoKey] !== true) return false;
    if (!_buscaLanc) return true;
    return (
      String(l["Código da Conta"] ?? "").toLowerCase().includes(_buscaLanc) ||
      String(l["Descrição da Conta"] ?? "").toLowerCase().includes(_buscaLanc) ||
      String(l["Descrição"] ?? "").toLowerCase().includes(_buscaLanc) ||
      String(l["Centro de Custo"] ?? "").toLowerCase().includes(_buscaLanc)
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
                valor={todasLinhas.filter((r) => r._tipo === "divergencia").length}
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

            {/* Abas principais */}
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
                  <div style={{ display: "flex", flexDirection: "column", gap: "var(--g-space-1)" }}>
                    <div className="g-cluster" style={{ gap: "var(--g-space-1)" }}>
                      {[["todos", "Todos"], ["divergencia", "Divergências"], ["ok", "OK"]].map(([val, label]) => (
                        <button
                          key={val}
                          className={`g-pill${filtro === val ? " g-pill--active" : ""}`}
                          onClick={() => mudarFiltro(val)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    {(filtro === "todos" || filtro === "so_sped" || filtro === "so_sap") && (
                      <div className="g-cluster" style={{ gap: "var(--g-space-1)", paddingLeft: "var(--g-space-3)" }}>
                        <span className="g-helper" style={{ fontSize: 11 }}>↳</span>
                        {[["so_sped", "Só SPED"], ["so_sap", "Só SAP"]].map(([val, label]) => (
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
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--g-space-2)" }}>
                    <input
                      className="g-input"
                      style={{ width: 260 }}
                      placeholder="Buscar por nota, chave NF-e, conta F100 ou bloco…"
                      value={filtroTexto}
                      onChange={(e) => { setFiltroTexto(e.target.value); setPaginaComp(1); }}
                    />
                    {filtroTexto && (
                      <button
                        className="g-btn g-btn--sm"
                        onClick={() => { setFiltroTexto(""); setPaginaComp(1); }}
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
                        <th>Tipo</th>
                        <th></th>
                        {TAXAS.map((t) => (
                          <th key={t}>{TAXA_LABELS[t]}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {linhasPag.length === 0 && (
                        <tr>
                          <td colSpan={TAXAS.length + 5} className="g-empty">
                            Nenhum resultado.
                          </td>
                        </tr>
                      )}
                      {linhasPag.map((row, i) => (
                        <tr
                          key={i}
                          className={
                            row._tipo === "divergencia" ? "app-row-diff" : ""
                          }
                        >
                          <td>
                            {row.NUM_DOC != null ? (
                              row.NUM_DOC
                            ) : row.COD_CTA != null ? (
                              <code className="g-mono" style={{ fontSize: 11 }}>
                                {row.COD_CTA}
                              </code>
                            ) : "—"}
                          </td>
                          <td>
                            {row.CHV_NFE || row.CHV_CTE ? (
                              <code className="g-mono" style={{ fontSize: 11 }}>
                                {row.CHV_NFE ?? row.CHV_CTE}
                              </code>
                            ) : row.NOME_CONTA ? (
                              <span style={{ fontSize: 12 }}>{row.NOME_CONTA}</span>
                            ) : "—"}
                          </td>
                          <td>
                            {(() => { const b = _bloco(row); return (
                              <span className={`app-bloco ${BLOCO_CLASS[b]}`}>
                                {BLOCO_LABEL[b]}
                              </span>
                            ); })()}
                          </td>
                          <td>
                            <span
                              className={`g-badge ${TIPO_BADGE[row._tipo]}`}
                            >
                              {TIPO_LABELS[row._tipo]}
                            </span>
                          </td>
                          <td className="app-td-origem">
                            {row._tipo === "so_sap" ? (
                              <span>SAP</span>
                            ) : row._tipo === "so_sped" ? (
                              <span>SPED</span>
                            ) : (
                              <>
                                <span>SPED</span>
                                <br />
                                <span className="g-helper">SAP</span>
                              </>
                            )}
                          </td>
                          {TAXAS.map((taxa) => {
                            const spedKey = taxa;
                            const sapKey = taxa + "_SAP";
                            const deltaKey = taxa.replace("VL_", "DELTA_");
                            const delta = row[deltaKey];
                            const hasDelta =
                              delta != null && Math.abs(delta) > 0.05;
                            return (
                              <td
                                key={taxa}
                                className={hasDelta ? "app-td-diff" : ""}
                              >
                                {row._tipo === "so_sap" ? (
                                  <span>{fmt(row[sapKey])}</span>
                                ) : row._tipo === "so_sped" ? (
                                  <span>{fmt(row[spedKey])}</span>
                                ) : row._tipo === "ok" ? (
                                  <>
                                    <span>{fmt(row[spedKey])}</span>
                                    <br />
                                    <span className="g-helper">
                                      {fmt(row[sapKey])}
                                    </span>
                                  </>
                                ) : (
                                  <>
                                    <span>{fmt(row[spedKey])}</span>
                                    <br />
                                    <span className="g-helper">
                                      {fmt(row[sapKey])}
                                    </span>
                                    {hasDelta && (
                                      <>
                                        <br />
                                        <span
                                          style={{
                                            fontSize: 10,
                                            color: "var(--g-warn-fg)",
                                          }}
                                        >
                                          Δ {fmt(delta)}
                                        </span>
                                      </>
                                    )}
                                  </>
                                )}
                              </td>
                            );
                          })}
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
                    className="g-cluster"
                    style={{ gap: "var(--g-space-4)" }}
                  >
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
                    <label className="g-check" style={{ color: "var(--g-warn-fg)" }}>
                      <input
                        type="checkbox"
                        checked={incluirSoSped}
                        onChange={() => { setIncluirSoSped((v) => !v); setPaginaLanc(1); }}
                      />
                      Incluir Só SPED
                    </label>
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
                      onChange={(e) => { setFiltroLanc(e.target.value); setPaginaLanc(1); }}
                    />
                    {filtroLanc && (
                      <button
                        className="g-btn g-btn--sm"
                        onClick={() => { setFiltroLanc(""); setPaginaLanc(1); }}
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

                {incluirSoSped && (
                  <div className="app-alert-warn">
                    <strong>Atenção — lançamentos Só SPED:</strong> esses registros existem
                    apenas no SPED e não possuem contrapartida no SAP. Os códigos de conta
                    são apenas sugestões; verifique e preencha a conta de contrapartida
                    antes de importar no SAP.
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
                            <tr key={i} className={l._soSped ? "app-row-so-sped" : ""}>
                              <td>
                                <code className="g-mono">
                                  {l["Código da Conta"]}
                                </code>
                              </td>
                              <td>{l["Descrição da Conta"]}</td>
                              <td
                                className={
                                  l["Débito"] != null ? "app-td-debito" : ""
                                }
                              >
                                {fmt(l["Débito"])}
                              </td>
                              <td
                                className={
                                  l["Crédito"] != null ? "app-td-credito" : ""
                                }
                              >
                                {fmt(l["Crédito"])}
                              </td>
                              <td>{l["Descrição"]}</td>
                              <td>{l["Centro de Custo"]}</td>
                              <td>{l["Filial"]}</td>
                              <td>
                                <span className="g-badge g-badge--neutral">
                                  {l["Imposto"]}
                                </span>
                              </td>
                              <td className="g-helper">{l["Sentido"]}</td>
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
