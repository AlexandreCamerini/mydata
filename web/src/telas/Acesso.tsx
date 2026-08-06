// A camada de acesso do ADR-19, com a tela que ela precisa.
//
// Duas listas e um botão. O que não é óbvio, e por isso está escrito na tela:
// registrar um segundo autenticador é o caminho normal de sair do risco desta
// decisão — o primeiro perdido não pode ser o único.
import { useState } from "react";
import { api, type Passkey, type Sessao } from "../api";
import {
  Aviso, Botao, Campo, Carregando, Confirmar, Erro, Selo, Tabela, Vazio, useDados,
} from "../ui";
import { instante } from "../objetos";

/** base64url ↔ bytes. O WebAuthn fala binário; o JSON, não.
 *
 * O retorno é `ArrayBuffer` e não `Uint8Array` porque o TypeScript moderno
 * tipa `Uint8Array` sobre `ArrayBufferLike`, que admite `SharedArrayBuffer` —
 * e `BufferSource` não. */
function paraBytes(s: string): ArrayBuffer {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i += 1) bytes[i] = b.charCodeAt(i);
  return bytes.buffer;
}

function paraB64(b: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(b)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

export function Acesso() {
  const estado = useDados(() => api.acesso(), []);
  const [rotulo, setRotulo] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [registrando, setRegistrando] = useState(false);
  const [revogar, setRevogar] = useState<Passkey | null>(null);
  const [encerrar, setEncerrar] = useState<Sessao | null>(null);

  async function registrar() {
    setErro(null);
    setAviso(null);
    if (!rotulo.trim()) {
      setErro("Dê um rótulo ao autenticador. É ele que aparece na lista — e é a única forma de saber qual revogar depois.");
      return;
    }
    if (!window.PublicKeyCredential) {
      setErro("Este navegador não suporta passkey.");
      return;
    }
    setRegistrando(true);
    try {
      const o = await api.opcoesDePasskey(rotulo);
      const publicKey: PublicKeyCredentialCreationOptions = {
        ...(o as unknown as PublicKeyCredentialCreationOptions),
        challenge: paraBytes(o.challenge),
        user: { ...o.user, id: paraBytes(o.user.id) },
        excludeCredentials: (o.excludeCredentials ?? []).map((c) => ({
          ...c,
          id: paraBytes(c.id),
        })) as PublicKeyCredentialDescriptor[],
      };
      const cred = (await navigator.credentials.create({
        publicKey,
      })) as PublicKeyCredential | null;
      if (!cred) throw new Error("O autenticador não devolveu credencial.");
      const resp = cred.response as AuthenticatorAttestationResponse;
      await api.registrarPasskey(rotulo, {
        id: cred.id,
        rawId: paraB64(cred.rawId),
        type: cred.type,
        response: {
          clientDataJSON: paraB64(resp.clientDataJSON),
          attestationObject: paraB64(resp.attestationObject),
          transports: resp.getTransports?.() ?? [],
        },
      });
      setRotulo("");
      setAviso(`"${rotulo}" registrado.`);
      estado.recarregar();
    } catch (e) {
      const err = e as Error;
      setErro(
        err.name === "NotAllowedError"
          ? "Registro cancelado no autenticador."
          : err.message,
      );
    } finally {
      setRegistrando(false);
    }
  }

  if (estado.carregando && !estado.dados) return <Carregando oque="a camada de acesso" />;
  if (estado.erro) return <Erro mensagem={estado.erro} />;
  if (!estado.dados) return null;

  const d = estado.dados.dados;

  return (
    <div className="grid gap-6">
      {!d.token_configurado && (
        <Aviso>
          `PORTAL_ADMIN_TOKEN` não está definido: em desenvolvimento local a
          administração fica aberta, e é por isso que esta tela abriu sem
          pedir nada. Em produção a variável é obrigatória.
        </Aviso>
      )}

      {d.passkeys.length === 1 && (
        <Aviso>
          Só um autenticador registrado. Registre um segundo — em outro
          aparelho — antes de precisar dele. É a saída mais barata do risco
          desta decisão; a outra é definir `PORTAL_ACESSO_LEGADO=1` no painel
          do Railway às onze da noite.
        </Aviso>
      )}

      <section aria-labelledby="como" className="grid gap-2">
        <h2 id="como" className="font-medium">
          Como se entra hoje
        </h2>
        <dl className="grid gap-3 sm:grid-cols-3 text-sm">
          <div className="border border-borda rounded bg-superficie p-3">
            <dt className="rotulo">Passkey</dt>
            <dd>
              {d.passkeys.length > 0 ? (
                <>
                  {d.passkeys.length} autenticador
                  {d.passkeys.length > 1 ? "es" : ""} registrado
                  {d.passkeys.length > 1 ? "s" : ""}
                </>
              ) : (
                "nenhum ainda"
              )}
              <span className="block text-xs text-tinta-suave mt-1">
                identidade <span className="font-mono">{d.identidade}</span>
              </span>
            </dd>
          </div>
          <div className="border border-borda rounded bg-superficie p-3">
            <dt className="rotulo">Formulário de token</dt>
            <dd>
              <Selo texto={d.token_no_formulario ? "visível" : "escondido"} />
              <span className="block text-xs text-tinta-suave mt-1">
                {d.acesso_legado
                  ? "PORTAL_ACESSO_LEGADO=1 o trouxe de volta"
                  : d.token_no_formulario
                    ? "some assim que o primeiro passkey entrar"
                    : "há passkey registrada"}
              </span>
            </dd>
          </div>
          <div className="border border-borda rounded bg-superficie p-3">
            <dt className="rotulo">Cabeçalho X-Admin-Token</dt>
            <dd>
              <Selo texto={d.token_configurado ? "sempre vale" : "sem token"} />
              <span className="block text-xs text-tinta-suave mt-1">
                para curl e script, que não têm navegador
              </span>
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="registrar" className="grid gap-3">
        <h2 id="registrar" className="font-medium">
          Registrar um autenticador
        </h2>
        <div className="border border-borda rounded bg-superficie p-4 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <Campo
            rotulo="Rótulo"
            valor={rotulo}
            aoMudar={setRotulo}
            ajuda="Onde ele mora — “notebook”, “telefone”, “chaveiro”. É o nome que aparece na lista e o que permite revogar o certo."
          />
          <div className="mb-4">
            <Botao variante="primario" carregando={registrando} aoClicar={registrar}>
              Registrar
            </Botao>
          </div>
        </div>
        {erro && <Erro mensagem={erro} />}
        {aviso && (
          <p role="status" className="text-sm text-ok">
            {aviso}
          </p>
        )}
      </section>

      <section aria-labelledby="autenticadores" className="grid gap-2">
        <h2 id="autenticadores" className="font-medium">
          Autenticadores
        </h2>
        {d.passkeys.length === 0 ? (
          <Vazio
            titulo="Nenhum autenticador registrado"
            dica="Enquanto não houver, a entrada continua pelo token — é assim que o primeiro entra."
          />
        ) : (
          <Tabela
            legenda="Passkeys registradas"
            colunas={["Rótulo", "Registrado em", "Último uso", "Onde", ""]}
          >
            {d.passkeys.map((p: Passkey) => (
              <tr key={p.credential_id} className="border-b border-borda last:border-0">
                <th scope="row" className="text-left px-3 py-2">
                  {p.rotulo}
                  <span className="block text-xs text-tinta-suave font-mono break-all">
                    {p.credential_id.slice(0, 16)}…
                  </span>
                </th>
                <td className="px-3 py-2 text-xs" title={instante(p.criada_em)}>
                  {p.criada_em?.slice(0, 10) ?? "—"}
                </td>
                <td className="px-3 py-2 text-xs" title={instante(p.ultimo_uso_em)}>
                  {p.ultimo_uso_em?.slice(0, 16).replace("T", " ") ?? "nunca"}
                </td>
                <td className="px-3 py-2 text-xs">{p.transportes || "—"}</td>
                <td className="px-3 py-2">
                  <Botao aoClicar={() => setRevogar(p)}>Revogar</Botao>
                </td>
              </tr>
            ))}
          </Tabela>
        )}
      </section>

      <section aria-labelledby="sessoes" className="grid gap-2">
        <h2 id="sessoes" className="font-medium">
          Sessões abertas
        </h2>
        <p className="text-sm text-tinta-suave">
          Cada uma diz por onde entrou. Encerrar uma não derruba as outras — era
          isso que faltava quando o token era a sessão.
        </p>
        {d.sessoes.length === 0 ? (
          <Vazio titulo="Nenhuma sessão aberta" />
        ) : (
          <Tabela
            legenda="Sessões de administração"
            colunas={["Entrou por", "Aberta em", "Último uso", "Expira em", ""]}
          >
            {d.sessoes.map((s: Sessao) => (
              <tr key={s.id} className="border-b border-borda last:border-0">
                <th scope="row" className="text-left px-3 py-2 font-mono text-xs">
                  {s.origem}
                </th>
                <td className="px-3 py-2 text-xs" title={instante(s.criada_em)}>
                  {s.criada_em?.slice(0, 16).replace("T", " ") ?? "—"}
                </td>
                <td className="px-3 py-2 text-xs" title={instante(s.ultimo_uso_em)}>
                  {s.ultimo_uso_em?.slice(0, 16).replace("T", " ") ?? "nunca"}
                </td>
                <td className="px-3 py-2 text-xs" title={instante(s.expira_em)}>
                  {s.expira_em?.slice(0, 10) ?? "—"}
                </td>
                <td className="px-3 py-2">
                  <Botao aoClicar={() => setEncerrar(s)}>Encerrar</Botao>
                </td>
              </tr>
            ))}
          </Tabela>
        )}
      </section>

      {/* Revogar é apagar. Se for o último autenticador e o token estiver
          escondido, a próxima entrada pelo navegador deixa de existir — e é
          melhor dizer isso antes do clique, não depois. */}
      <Confirmar
        aberto={revogar !== null}
        titulo="Revogar autenticador"
        objeto={revogar?.rotulo ?? ""}
        consequencia={
          d.passkeys.length === 1
            ? `É o único registrado. Depois disto, entrar pelo navegador exige o token, que está ${d.token_no_formulario ? "visível na tela de entrada" : "escondido — seria preciso definir PORTAL_ACESSO_LEGADO=1"}. Vai apagar`
            : `Os outros ${d.passkeys.length - 1} continuam valendo. Vai apagar`
        }
        aoConfirmar={async () => {
          const alvo = revogar!;
          setRevogar(null);
          await api.revogarPasskey(alvo.credential_id);
          estado.recarregar();
        }}
        aoCancelar={() => setRevogar(null)}
      />

      <Confirmar
        aberto={encerrar !== null}
        titulo="Encerrar sessão"
        objeto={encerrar?.origem ?? ""}
        consequencia="Se for a sua, você cai na tela de entrada. Vai encerrar"
        aoConfirmar={async () => {
          const alvo = encerrar!;
          setEncerrar(null);
          await api.encerrarSessao(alvo.id);
          estado.recarregar();
        }}
        aoCancelar={() => setEncerrar(null)}
      />
    </div>
  );
}
