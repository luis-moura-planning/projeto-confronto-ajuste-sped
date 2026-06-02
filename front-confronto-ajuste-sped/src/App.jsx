import { useRef, useState } from "react";
import * as XLSX from "xlsx";
import "./App.css";

const TAXAS = ["VL_ITEM", "VL_ICMS", "VL_PIS", "VL_COFINS"];
const TAXA_LABELS = {
  VL_ITEM:   "Vlr. Item",
  VL_ICMS:   "ICMS",
  VL_PIS:    "PIS",
  VL_COFINS: "COFINS",
};

const IMPOSTOS_LANC = [
  { campo: "ITEM",   label: "Item" },
  { campo: "ICMS",   label: "ICMS" },
  { campo: "PIS",    label: "PIS" },
  { campo: "COFINS", label: "COFINS" },
];

const TIPO_BADGE = {
  divergencia: "g-badge--warn",
  so_sped:     "g-badge--danger",
  so_sap:      "g-badge--neutral",
};
const TIPO_LABELS = {
  divergencia: "Divergência",
  so_sped:     "Só SPED",
  so_sap:      "Só SAP",
};

const OPCOES_POR_PAGINA = [10, 20, 50, 100];

function fmt(val) {
  if (val == null) return "—";
  const n = Number(val);
  if (isNaN(n)) return "—";
  return n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function exportarXLSX(lancamentos) {
  const cols = [
    "Código da Conta", "Descrição da Conta", "Débito", "Crédito",
    "Descrição", "Centro de Custo", "Filial", "Imposto", "Sentido",
  ];
  const dados = lancamentos.map(l =>
    Object.fromEntries(cols.map(k => [k, l[k] ?? ""]))
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
  const [impostosAtivos, setImpostosAtivos] = useState(
    () => Object.fromEntries(IMPOSTOS_LANC.map(i => [i.campo, true]))
  );

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
        ...(resultado.divergencias ?? []).map(r => ({ ...r, _tipo: "divergencia" })),
        ...(resultado.so_sped ?? []).map(r => ({ ...r, _tipo: "so_sped" })),
        ...(resultado.so_sap ?? []).map(r => ({ ...r, _tipo: "so_sap" })),
      ]
    : [];

  const linhasFiltradas = todasLinhas.filter(
    r => filtro === "todos" || r._tipo === filtro
  );

  const totalPagsComp = Math.max(1, Math.ceil(linhasFiltradas.length / porPaginaComp));
  const linhasPag = linhasFiltradas.slice(
    (paginaComp - 1) * porPaginaComp,
    paginaComp * porPaginaComp
  );

  const lancamentos = (resultado?.lancamentos ?? []).filter(
    l => impostosAtivos[l["Imposto"]] !== false
  );
  const totalPagsLanc = Math.max(1, Math.ceil(lancamentos.length / porPaginaLanc));
  const lancPag = lancamentos.slice(
    (paginaLanc - 1) * porPaginaLanc,
    paginaLanc * porPaginaLanc
  );

  function toggleImposto(campo) {
    setImpostosAtivos(prev => ({ ...prev, [campo]: !prev[campo] }));
    setPaginaLanc(1);
  }

  return (
    <div>
      <nav className="g-navbar">
        <div className="g-navbar__brand">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
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
        <span className="g-helper g-hidden-sm">Comparação de lançamentos contábeis</span>
      </nav>

      <main
        className="g-container"
        style={{ marginTop: "var(--g-space-8)", marginBottom: "var(--g-space-8)" }}
      >
        <form
          className="g-section"
          onSubmit={handleSubmit}
          style={{ display: "flex", flexDirection: "column", gap: "var(--g-space-5)" }}
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
            style={{ display: "flex", flexDirection: "column", gap: "var(--g-space-5)" }}
          >
            {/* Cards de resumo */}
            <div className="g-grid g-grid--auto-160">
              <ResumoCard label="Divergências"  valor={(resultado.divergencias ?? []).length} cor="warn" />
              <ResumoCard label="Só no SPED"    valor={(resultado.so_sped ?? []).length}       cor="danger" />
              <ResumoCard label="Só no SAP"     valor={(resultado.so_sap ?? []).length}         cor="" />
              <ResumoCard label="Lançamentos"   valor={(resultado.lancamentos ?? []).length}    cor="success" />
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
                  <span className="g-badge g-badge--neutral" style={{ marginLeft: 6 }}>
                    {lancamentos.length}
                  </span>
                )}
              </button>
            </div>

            {/* ── Aba: Comparação ── */}
            {abaAtiva === "comparacao" && (
              <>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "var(--g-space-2)" }}>
                  <div className="g-cluster" style={{ gap: "var(--g-space-1)" }}>
                    {[
                      ["todos",       "Todos"],
                      ["divergencia", "Divergências"],
                      ["so_sped",     "Só SPED"],
                      ["so_sap",      "Só SAP"],
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
                  <span className="g-helper">
                    {linhasFiltradas.length} registro{linhasFiltradas.length !== 1 ? "s" : ""}
                  </span>
                </div>

                <BarraPaginacao
                  pagina={paginaComp}
                  total={totalPagsComp}
                  porPagina={porPaginaComp}
                  totalItens={linhasFiltradas.length}
                  onPagina={setPaginaComp}
                  onPorPagina={v => { setPorPaginaComp(v); setPaginaComp(1); }}
                />

                <div className="g-table-wrap">
                  <table className="g-table">
                    <thead>
                      <tr>
                        <th>Nota</th>
                        <th>Chave NF-e</th>
                        <th>Tipo</th>
                        <th></th>
                        {TAXAS.map(t => <th key={t}>{TAXA_LABELS[t]}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {linhasPag.length === 0 && (
                        <tr>
                          <td colSpan={TAXAS.length + 4} className="g-empty">
                            Nenhum resultado.
                          </td>
                        </tr>
                      )}
                      {linhasPag.map((row, i) => (
                        <tr key={i} className={row._tipo === "divergencia" ? "app-row-diff" : ""}>
                          <td>{row.NUM_DOC ?? "—"}</td>
                          <td>
                            <code className="g-mono" style={{ fontSize: 11 }}>
                              {row.CHV_NFE ?? "—"}
                            </code>
                          </td>
                          <td>
                            <span className={`g-badge ${TIPO_BADGE[row._tipo]}`}>
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
                          {TAXAS.map(taxa => {
                            const spedKey  = taxa;
                            const sapKey   = taxa + "_SAP";
                            const deltaKey = taxa.replace("VL_", "DELTA_");
                            const delta    = row[deltaKey];
                            const hasDelta = delta != null && Math.abs(delta) > 0.05;
                            return (
                              <td key={taxa} className={hasDelta ? "app-td-diff" : ""}>
                                {row._tipo === "so_sap" ? (
                                  <span>{fmt(row[sapKey])}</span>
                                ) : row._tipo === "so_sped" ? (
                                  <span>{fmt(row[spedKey])}</span>
                                ) : (
                                  <>
                                    <span>{fmt(row[spedKey])}</span>
                                    <br />
                                    <span className="g-helper">{fmt(row[sapKey])}</span>
                                    {hasDelta && (
                                      <>
                                        <br />
                                        <span style={{ fontSize: 10, color: "var(--g-warn-fg)" }}>
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
                  onPorPagina={v => { setPorPaginaComp(v); setPaginaComp(1); }}
                />
              </>
            )}

            {/* ── Aba: Lançamentos ── */}
            {abaAtiva === "lancamentos" && (
              <>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "var(--g-space-3)" }}>
                  <div className="g-cluster" style={{ gap: "var(--g-space-4)" }}>
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
                  <div className="g-cluster" style={{ gap: "var(--g-space-2)" }}>
                    <span className="g-helper">
                      {lancamentos.length} lançamento{lancamentos.length !== 1 ? "s" : ""}
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

                {lancamentos.length === 0 ? (
                  <p className="g-empty">Nenhum lançamento gerado — sem diferenças encontradas.</p>
                ) : (
                  <>
                    <BarraPaginacao
                      pagina={paginaLanc}
                      total={totalPagsLanc}
                      porPagina={porPaginaLanc}
                      totalItens={lancamentos.length}
                      onPagina={setPaginaLanc}
                      onPorPagina={v => { setPorPaginaLanc(v); setPaginaLanc(1); }}
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
                            <tr key={i}>
                              <td><code className="g-mono">{l["Código da Conta"]}</code></td>
                              <td>{l["Descrição da Conta"]}</td>
                              <td className={l["Débito"] != null ? "app-td-debito" : ""}>
                                {fmt(l["Débito"])}
                              </td>
                              <td className={l["Crédito"] != null ? "app-td-credito" : ""}>
                                {fmt(l["Crédito"])}
                              </td>
                              <td>{l["Descrição"]}</td>
                              <td>{l["Centro de Custo"]}</td>
                              <td>{l["Filial"]}</td>
                              <td>
                                <span className="g-badge g-badge--neutral">{l["Imposto"]}</span>
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
                      onPorPagina={v => { setPorPaginaLanc(v); setPaginaLanc(1); }}
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

function BarraPaginacao({ pagina, total, porPagina, totalItens, onPagina, onPorPagina }) {
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
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "var(--g-space-2)" }}>
      <div className="g-cluster" style={{ gap: "var(--g-space-2)" }}>
        <span className="g-helper">
          {inicio}–{fim} de {totalItens}
        </span>
        <select
          className="g-select"
          style={{ width: "auto", padding: "4px 8px" }}
          value={porPagina}
          onChange={e => onPorPagina(Number(e.target.value))}
        >
          {OPCOES_POR_PAGINA.map(n => (
            <option key={n} value={n}>{n} por página</option>
          ))}
        </select>
      </div>

      {total > 1 && (
        <div className="g-cluster" style={{ gap: "var(--g-space-1)" }}>
          <button className="g-btn g-btn--sm" disabled={pagina === 1} onClick={() => onPagina(pagina - 1)}>‹</button>
          {pages.map((p, i) =>
            p === "..." ? (
              <span key={`e${i}`} className="g-helper" style={{ padding: "0 4px" }}>…</span>
            ) : (
              <button
                key={p}
                className={`g-btn g-btn--sm${p === pagina ? " g-btn--primary" : ""}`}
                onClick={() => onPagina(p)}
              >
                {p}
              </button>
            )
          )}
          <button className="g-btn g-btn--sm" disabled={pagina === total} onClick={() => onPagina(pagina + 1)}>›</button>
        </div>
      )}
    </div>
  );
}

function DropField({ label, required, accept, file, inputRef, onChange, hint }) {
  return (
    <div className="g-field">
      <label className="g-field__label">
        {label}{" "}
        {required && <span style={{ color: "var(--g-danger)" }}>*</span>}
      </label>
      <div
        className={`app-drop-zone${file ? " app-drop-zone--filled" : ""}`}
        onDragOver={e => e.preventDefault()}
        onDrop={e => { e.preventDefault(); onChange(e.dataTransfer.files[0]); }}
        onClick={() => inputRef.current?.click()}
      >
        {file ? file.name : hint}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        hidden
        onChange={e => onChange(e.target.files[0])}
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
