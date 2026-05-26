import { useState, useRef } from 'react'
import './App.css'

const CAMPOS = ['vl_doc', 'vl_icms', 'vl_pis', 'vl_cofins', 'vl_cbs', 'vl_ibs']

const STATUS_LABELS = { encontrado: 'Encontrado', sem_sped: 'Sem SPED', sem_sap: 'Sem SAP' }
const STATUS_CLASS  = { encontrado: 'badge-ok', sem_sped: 'badge-warn', sem_sap: 'badge-err' }

function fmt(val) {
  if (val == null) return '—'
  return val.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function temDif(row) {
  return row.diferenca && CAMPOS.some(c => row.diferenca[c] !== 0)
}

function fmtNum(val) {
  if (val == null) return ''
  return String(val).replace('.', ',')
}

function csvCell(val) {
  if (val == null) return ''
  const s = String(val)
  return s.includes(';') || s.includes('"') || s.includes('\n')
    ? `"${s.replace(/"/g, '""')}"`
    : s
}

function exportarCSV(lancamentos) {
  const cabecalho = ['Nota', 'Código Conta', 'Descrição', 'Débito', 'Crédito', 'Centro de Custo', 'Filial']
  const linhas = lancamentos.map(l => [
    csvCell(l.nota),
    csvCell(l.codigo_conta),
    csvCell(l.descricao_conta),
    fmtNum(l.debito),
    fmtNum(l.credito),
    csvCell(l.centro_custo),
    csvCell(l.filial),
  ].join(';'))

  const csv = '﻿' + [cabecalho.join(';'), ...linhas].join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = 'lancamentos_diferenca.csv'
  a.click()
  URL.revokeObjectURL(url)
}

export default function App() {
  const [sapFile,   setSapFile]   = useState(null)
  const [spedFile,  setSpedFile]  = useState(null)
  const [filial,    setFilial]    = useState('')
  const [mapJson,   setMapJson]   = useState('')
  const [avancado,  setAvancado]  = useState(false)
  const [loading,   setLoading]   = useState(false)
  const [erro,      setErro]      = useState(null)
  const [resultado, setResultado] = useState(null)
  const [filtro,    setFiltro]    = useState('todos')

  const sapRef  = useRef(null)
  const spedRef = useRef(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!sapFile || !spedFile) return

    setLoading(true)
    setErro(null)
    setResultado(null)

    const form = new FormData()
    form.append('planilha_sap',        sapFile)
    form.append('sped_contribuicoes',  spedFile)
    form.append('filial',              filial)
    form.append('mapeamento', mapJson || '{}')

    try {
      const res  = await fetch('/api/comparar/compara_planilha_sped', { method: 'POST', body: form })
      const data = await res.json()
      if (!res.ok) setErro(data.detail ?? 'Erro ao processar arquivos.')
      else         setResultado(data)
    } catch {
      setErro('Falha na comunicação com o servidor.')
    } finally {
      setLoading(false)
    }
  }

  const linhas = resultado
    ? Object.entries(resultado.comparacao).filter(
        ([, v]) => filtro === 'todos' || v.status === filtro
      )
    : []

  return (
    <div className="app">
      <header className="app-header">
        <h1>Confronto SAP × SPED</h1>
        <p>Comparação de lançamentos contábeis entre planilha SAP e arquivo SPED Contribuições</p>
      </header>

      <main className="app-main">
        <form className="card form-card" onSubmit={handleSubmit}>
          <h2>Arquivos</h2>

          <div className="form-row">
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

          <div className="form-row">
            <label className="field">
              <span>Filial</span>
              <input type="text" value={filial} onChange={e => setFilial(e.target.value)} placeholder="ex: CENTRAL IRRIGACAO LTDA" />
            </label>
          </div>

          <button type="button" className="btn-link" onClick={() => setAvancado(v => !v)}>
            {avancado ? '▲ Ocultar opções avançadas' : '▼ Opções avançadas'}
          </button>

          {avancado && (
            <div className="avancado-grid">
              <label className="field">
                <span>Mapeamento SAP → SPED <small>(JSON)</small></span>
                <textarea
                  rows={5}
                  value={mapJson}
                  onChange={e => setMapJson(e.target.value)}
                  placeholder={'{\n  "NS 5882": "38676"\n}'}
                />
              </label>
            </div>
          )}

          {erro && <div className="alert-err">{erro}</div>}

          <button type="submit" className="btn-primary" disabled={loading || !sapFile || !spedFile}>
            {loading ? 'Processando...' : 'Comparar'}
          </button>
        </form>

        {resultado && (
          <section className="resultado">
            <div className="resultado-toolbar">
              <button
                type="button"
                className="btn-export"
                disabled={!resultado.lancamentos?.length}
                onClick={() => exportarCSV(resultado.lancamentos)}
              >
                Exportar Lançamentos CSV
              </button>
            </div>

            <div className="resumo-grid">
              <ResumoCard label="Notas SAP"    valor={resultado.resumo.total_notas_sap}  />
              <ResumoCard label="Notas SPED"   valor={resultado.resumo.total_notas_sped} />
              <ResumoCard label="Encontrados"  valor={resultado.resumo.encontrados}      cor="ok"   />
              <ResumoCard label="Sem SPED"     valor={resultado.resumo.sem_sped}         cor="warn" />
              <ResumoCard label="Sem SAP"      valor={resultado.resumo.sem_sap}          cor="err"  />
            </div>

            <div className="tabs">
              {[
                ['todos',     'Todos'],
                ['encontrado','Encontrados'],
                ['sem_sped',  'Sem SPED'],
                ['sem_sap',   'Sem SAP'],
              ].map(([val, label]) => (
                <button key={val} className={`tab ${filtro === val ? 'active' : ''}`} onClick={() => setFiltro(val)}>
                  {label}
                </button>
              ))}
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Chave SAP</th>
                    <th>Chave SPED</th>
                    <th>Status</th>
                    {CAMPOS.map(c => <th key={c}>{c}</th>)}
                    <th>Dif. Total</th>
                  </tr>
                </thead>
                <tbody>
                  {linhas.length === 0 && (
                    <tr><td colSpan={CAMPOS.length + 4} className="td-vazio">Nenhum resultado.</td></tr>
                  )}
                  {linhas.map(([chave, row]) => {
                    const difTotal = row.diferenca
                      ? CAMPOS.reduce((s, c) => s + (row.diferenca[c] ?? 0), 0)
                      : null
                    return (
                      <tr key={chave} className={temDif(row) ? 'row-diff' : ''}>
                        <td>{row.chave_sap  ?? '—'}</td>
                        <td>{row.chave_sped ?? '—'}</td>
                        <td><span className={`badge ${STATUS_CLASS[row.status]}`}>{STATUS_LABELS[row.status]}</span></td>
                        {CAMPOS.map(c => (
                          <td key={c} className={row.diferenca?.[c] !== 0 ? 'td-diff' : ''}>
                            <span className="val-sap">{fmt(row.sap?.[c])}</span>
                            {row.sped && <><br /><span className="val-sped">{fmt(row.sped[c])}</span></>}
                          </td>
                        ))}
                        <td className={difTotal && difTotal !== 0 ? 'td-diff' : ''}>{fmt(difTotal)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {resultado.lancamentos?.length > 0 && (
              <>
                <h2>Lançamentos Gerados</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Nota</th>
                        <th>Conta</th>
                        <th>Descrição</th>
                        <th>Débito</th>
                        <th>Crédito</th>
                        <th>Centro Custo</th>
                        <th>Filial</th>
                      </tr>
                    </thead>
                    <tbody>
                      {resultado.lancamentos.map((l, i) => (
                        <tr key={i}>
                          <td>{l.nota}</td>
                          <td><code>{l.codigo_conta}</code></td>
                          <td>{l.descricao_conta}</td>
                          <td className={l.debito  != null ? 'td-debito'  : ''}>{fmt(l.debito)}</td>
                          <td className={l.credito != null ? 'td-credito' : ''}>{fmt(l.credito)}</td>
                          <td>{l.centro_custo}</td>
                          <td>{l.filial}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        )}
      </main>
    </div>
  )
}

function DropField({ label, required, accept, file, inputRef, onChange, hint }) {
  return (
    <label className="field">
      <span>{label} {required && <span className="req">*</span>}</span>
      <div
        className={`drop-zone ${file ? 'filled' : ''}`}
        onDragOver={e => e.preventDefault()}
        onDrop={e => { e.preventDefault(); onChange(e.dataTransfer.files[0]) }}
      >
        {file ? file.name : hint}
      </div>
      <input ref={inputRef} type="file" accept={accept} hidden onChange={e => onChange(e.target.files[0])} />
    </label>
  )
}

function ResumoCard({ label, valor, cor }) {
  return (
    <div className={`resumo-card ${cor ? `resumo-${cor}` : ''}`}>
      <span className="resumo-num">{valor}</span>
      <span className="resumo-label">{label}</span>
    </div>
  )
}
