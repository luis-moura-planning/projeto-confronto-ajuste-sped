import { useRef, useState } from "react";
import * as XLSX from "xlsx";
import "./App.css";

const CAMPOS = ["vl_doc", "vl_icms", "vl_pis", "vl_cofins", "vl_cbs", "vl_ibs"];

const CAMPOS_LABELS = {
  vl_doc:    "Vlr. Documento",
  vl_icms:   "ICMS",
  vl_pis:    "PIS",
  vl_cofins: "COFINS",
  vl_cbs:    "CBS",
  vl_ibs:    "IBS",
};

const STATUS_LABELS = {
  encontrado: "Encontrado",
  sem_sped: "Sem SPED",
  sem_sap: "Sem SAP",
};
const STATUS_BADGE = {
  encontrado: "g-badge--success",
  sem_sped: "g-badge--warn",
  sem_sap: "g-badge--danger",
};

const OPCOES_POR_PAGINA = [10, 20, 50, 100];

function fmt(val) {
  if (val == null) return "—";
  return val.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function temDif(row) {
  return row.diferenca && CAMPOS.some((c) => row.diferenca[c] !== 0);
}

function exportarXLSX(lancamentos) {
  const dados = lancamentos.map((l) => ({
    "Código da Conta": l.codigo_conta ?? "",
    "Descrição da Conta": l.descricao_conta ?? "",
    Débito: l.debito ?? "",
    Crédito: l.credito ?? "",
    Descrição: l.descricao ?? "",
    "Centro de Custo": l.centro_custo ?? "",
    Filial: l.filial ?? "",
  }));

  const ws = XLSX.utils.json_to_sheet(dados);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Lançamentos");
  XLSX.writeFile(wb, "lancamentos_diferenca.xlsx");
}

export default function App() {
  const [sapFile, setSapFile] = useState(null);
  const [spedFile, setSpedFile] = useState(null);
  const [filial, setFilial] = useState("");
  const [mapJson, setMapJson] = useState("");
  const [avancado, setAvancado] = useState(false);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState(null);
  const [resultado, setResultado] = useState(null);
  const [filtro, setFiltro] = useState("todos");
  const [abaAtiva, setAbaAtiva] = useState("comparacao");
  const [paginaComp, setPaginaComp] = useState(1);
  const [paginaLanc, setPaginaLanc] = useState(1);
  const [porPaginaComp, setPorPaginaComp] = useState(20);
  const [porPaginaLanc, setPorPaginaLanc] = useState(20);

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
    form.append("filial", filial);
    form.append("mapeamento", mapJson || "{}");

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

  const linhas = resultado
    ? Object.entries(resultado.comparacao).filter(
        ([, v]) => filtro === "todos" || v.status === filtro,
      )
    : [];

  const totalPagsComp = Math.max(1, Math.ceil(linhas.length / porPaginaComp));
  const linhasPag = linhas.slice((paginaComp - 1) * porPaginaComp, paginaComp * porPaginaComp);

  const lancamentos = resultado?.lancamentos ?? [];
  const totalPagsLanc = Math.max(1, Math.ceil(lancamentos.length / porPaginaLanc));
  const lancPag = lancamentos.slice((paginaLanc - 1) * porPaginaLanc, paginaLanc * porPaginaLanc);

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

          <div className="g-form-grid">
            <div className="g-field">
              <label className="g-field__label">Filial</label>
              <input
                className="g-input"
                type="text"
                value={filial}
                onChange={(e) => setFilial(e.target.value)}
                placeholder="ex: CENTRAL IRRIGACAO LTDA"
              />
            </div>
          </div>

          <button
            type="button"
            className="g-btn g-btn--primary"
            onClick={() => setAvancado((v) => !v)}
          >
            {avancado ? "▲ Ocultar opções avançadas" : "▼ Opções avançadas"}
          </button>

          {avancado && (
            <div style={{ borderTop: "1px solid var(--g-border)", paddingTop: "var(--g-space-4)" }}>
              <div className="g-field">
                <label className="g-field__label">
                  Mapeamento SAP → SPED <small className="g-helper">(JSON)</small>
                </label>
                <textarea
                  className="g-textarea"
                  rows={5}
                  value={mapJson}
                  onChange={(e) => setMapJson(e.target.value)}
                  placeholder={'{\n  "NS 5882": "38676"\n}'}
                />
              </div>
            </div>
          )}

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
              <ResumoCard label="Notas SAP"   valor={resultado.resumo.total_notas_sap}  cor="" />
              <ResumoCard label="Notas SPED"  valor={resultado.resumo.total_notas_sped} cor="" />
              <ResumoCard label="Encontrados" valor={resultado.resumo.encontrados}       cor="success" />
              <ResumoCard label="Sem SPED"    valor={resultado.resumo.sem_sped}          cor="warn" />
              <ResumoCard label="Sem SAP"     valor={resultado.resumo.sem_sap}           cor="danger" />
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
                      ["todos", "Todos"],
                      ["encontrado", "Encontrados"],
                      ["sem_sped", "Sem SPED"],
                      ["sem_sap", "Sem SAP"],
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
                    {linhas.length} registro{linhas.length !== 1 ? "s" : ""}
                  </span>
                </div>

                <BarraPaginacao
                  pagina={paginaComp}
                  total={totalPagsComp}
                  porPagina={porPaginaComp}
                  totalItens={linhas.length}
                  onPagina={setPaginaComp}
                  onPorPagina={(v) => { setPorPaginaComp(v); setPaginaComp(1); }}
                />

                <div className="g-table-wrap">
                  <table className="g-table">
                    <thead>
                      <tr>
                        <th>Nota</th>
                        <th>Chave SPED</th>
                        <th>Status</th>
                        {CAMPOS.map((c) => (
                          <th key={c}>{CAMPOS_LABELS[c]}</th>
                        ))}
                        <th>Dif. Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {linhasPag.length === 0 && (
                        <tr>
                          <td colSpan={CAMPOS.length + 4} className="g-empty">
                            Nenhum resultado.
                          </td>
                        </tr>
                      )}
                      {linhasPag.map(([chave, row]) => {
                        const difTotal = row.diferenca
                          ? CAMPOS.reduce((s, c) => s + (row.diferenca[c] ?? 0), 0)
                          : null;
                        return (
                          <tr key={chave} className={temDif(row) ? "app-row-diff" : ""}>
                            <td>{row.chave_sap ?? "—"}</td>
                            <td>{row.chave_sped ?? "—"}</td>
                            <td>
                              <span className={`g-badge ${STATUS_BADGE[row.status]}`}>
                                {STATUS_LABELS[row.status]}
                              </span>
                            </td>
                            {CAMPOS.map((c) => (
                              <td key={c} className={row.diferenca?.[c] !== 0 ? "app-td-diff" : ""}>
                                <span>{fmt(row.sap?.[c])}</span>
                                {row.sped && (
                                  <>
                                    <br />
                                    <span className="g-helper">{fmt(row.sped[c])}</span>
                                  </>
                                )}
                              </td>
                            ))}
                            <td className={difTotal && difTotal !== 0 ? "app-td-diff" : ""}>
                              {fmt(difTotal)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <BarraPaginacao
                  pagina={paginaComp}
                  total={totalPagsComp}
                  porPagina={porPaginaComp}
                  totalItens={linhas.length}
                  onPagina={setPaginaComp}
                  onPorPagina={(v) => { setPorPaginaComp(v); setPaginaComp(1); }}
                />
              </>
            )}

            {/* ── Aba: Lançamentos ── */}
            {abaAtiva === "lancamentos" && (
              <>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "var(--g-space-2)" }}>
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
                      onPorPagina={(v) => { setPorPaginaLanc(v); setPaginaLanc(1); }}
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
                            <th>Centro de Custo</th>
                            <th>Filial</th>
                          </tr>
                        </thead>
                        <tbody>
                          {lancPag.map((l, i) => (
                            <tr key={i}>
                              <td><code className="g-mono">{l.codigo_conta}</code></td>
                              <td>{l.descricao_conta}</td>
                              <td className={l.debito  != null ? "app-td-debito"  : ""}>{fmt(l.debito)}</td>
                              <td className={l.credito != null ? "app-td-credito" : ""}>{fmt(l.credito)}</td>
                              <td>{l.descricao}</td>
                              <td>{l.centro_custo}</td>
                              <td>{l.filial}</td>
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
                      onPorPagina={(v) => { setPorPaginaLanc(v); setPaginaLanc(1); }}
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
      {/* Contador + select */}
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
            <option key={n} value={n}>{n} por página</option>
          ))}
        </select>
      </div>

      {/* Botões de página */}
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
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); onChange(e.dataTransfer.files[0]); }}
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
