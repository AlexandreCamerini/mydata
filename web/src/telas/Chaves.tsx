import { useState } from "react";
import { api, type Chave } from "../api";
import {
  Aviso, Botao, Campo, Carregando, Confirmar, Erro, Tabela, Vazio, useDados,
} from "../ui";

export function Chaves() {
  const { dados, erro, carregando, recarregar } = useDados(() => api.chaves());
  const [consumidor, setConsumidor] = useState("");
  const [quotaMinuto, setQuotaMinuto] = useState("120");
  const [quotaDia, setQuotaDia] = useState("50000");
  const [emitida, setEmitida] = useState<{ chave: string; aviso: string } | null>(null);
  const [erroForm, setErroForm] = useState<string | null>(null);
  const [emitindo, setEmitindo] = useState(false);
  const [revogar, setRevogar] = useState<Chave | null>(null);

  async function emitir(e: React.FormEvent) {
    e.preventDefault();
    if (!consumidor.trim()) {
      setErroForm("Informe o consumidor.");
      return;
    }
    setErroForm(null);
    setEmitindo(true);
    try {
      const r = await api.emitirChave(
        consumidor, Number(quotaMinuto), Number(quotaDia),
      );
      setEmitida(r.dados);
      setConsumidor("");
      recarregar();
    } catch (e) {
      setErroForm((e as Error).message);
    } finally {
      setEmitindo(false);
    }
  }

  async function confirmarRevogacao() {
    if (!revogar) return;
    const alvo = revogar;
    setRevogar(null);
    try {
      await api.revogarChave(alvo.prefixo);
      recarregar();
    } catch (e) {
      setErroForm((e as Error).message);
    }
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_340px]">
      <section aria-labelledby="lista-chaves">
        <h2 id="lista-chaves" className="font-medium mb-3">
          Consumidores
        </h2>
        {carregando && <Carregando oque="chaves" />}
        {erro && <Erro mensagem={erro} />}
        {dados && dados.dados.length === 0 && (
          <Vazio titulo="Nenhuma chave emitida" dica="Emita a primeira ao lado." />
        )}
        {dados && dados.dados.length > 0 && (
          <Tabela
            legenda="Chaves de API emitidas"
            colunas={["Consumidor", "Prefixo", "Quota/min", "Quota/dia", "Situação", "Ação"]}
          >
            {dados.dados.map((c: Chave) => (
              <tr key={c.id} className="border-b border-borda last:border-0">
                <th scope="row" className="text-left px-3 py-2">
                  {c.consumidor}
                </th>
                <td className="px-3 py-2 font-mono text-xs">{c.prefixo}</td>
                <td className="px-3 py-2 tabular-nums">{c.quota_minuto}</td>
                <td className="px-3 py-2 tabular-nums">{c.quota_dia}</td>
                <td className="px-3 py-2">
                  {c.revogada_em ? (
                    <span className="text-tinta-suave">revogada</span>
                  ) : (
                    <span className="text-ok">ativa</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {!c.revogada_em && (
                    <Botao variante="destrutivo" aoClicar={() => setRevogar(c)}>
                      Revogar
                    </Botao>
                  )}
                </td>
              </tr>
            ))}
          </Tabela>
        )}
      </section>

      <section aria-labelledby="nova-chave">
        <h2 id="nova-chave" className="font-medium mb-3">
          Emitir chave
        </h2>
        <form onSubmit={emitir} className="border border-borda rounded p-4 bg-white">
          {erroForm && <Erro mensagem={erroForm} />}
          <Campo
            rotulo="Consumidor"
            valor={consumidor}
            aoMudar={setConsumidor}
            obrigatorio
            ajuda="Quem vai usar esta chave. Ex.: bolsia."
          />
          <Campo
            rotulo="Quota por minuto"
            valor={quotaMinuto}
            aoMudar={setQuotaMinuto}
            tipo="number"
          />
          <Campo
            rotulo="Quota por dia"
            valor={quotaDia}
            aoMudar={setQuotaDia}
            tipo="number"
          />
          <Botao tipo="submit" variante="primario" carregando={emitindo}>
            Emitir
          </Botao>
        </form>

        {emitida && (
          <div role="status" className="mt-4">
            <Aviso>
              <p className="font-medium mb-1">{emitida.aviso}</p>
              <code className="block bg-gray-50 border border-borda rounded p-2 text-xs break-all">
                {emitida.chave}
              </code>
              <p className="text-xs text-tinta-suave mt-2">
                Guardamos apenas o hash. Perdida a chave, emita outra.
              </p>
            </Aviso>
          </div>
        )}
      </section>

      <Confirmar
        aberto={revogar !== null}
        titulo="Revogar chave de API"
        objeto={`${revogar?.consumidor} (${revogar?.prefixo})`}
        consequencia="As chamadas passarão a receber 401 imediatamente para"
        aoConfirmar={confirmarRevogacao}
        aoCancelar={() => setRevogar(null)}
      />
    </div>
  );
}
