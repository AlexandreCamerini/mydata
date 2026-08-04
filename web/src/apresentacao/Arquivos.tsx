// Os arquivos originais, com a digital que o leitor confere sozinho.
//
// Até `/v1/capturas/{id}/arquivo` existir, o SHA-256 na tela era um número
// que o usuário tinha de aceitar no fio do bigode: o único caminho oferecido
// era a URL da fonte, que é endereço mutável — a CVM regenera o arquivo a
// cada reapresentação, e baixar de novo não reproduz a captura de antes.
//
// Esta tela é a menor da apresentação e a que carrega a tese do produto.
import { Carregando, Erro, Tabela, Vazio, useDados } from "../ui";
import { api } from "./api";

function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const u = ["kB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${u[i]}`;
}

export function Arquivos({ cd_cvm }: { cd_cvm: number }) {
  const { dados, erro, carregando } = useDados(() => api.resumo(cd_cvm), [cd_cvm]);

  if (carregando && !dados) return <Carregando oque="os arquivos originais" />;
  if (erro) return <Erro mensagem={erro} />;
  if (!dados) return <Vazio titulo="Sem arquivos" />;

  const capturas = dados.dados.capturas;

  return (
    <div className="grid gap-4">
      <header className="grid gap-1">
        <p className="text-xs text-tinta-suave">
          <a href={`#/empresa/${cd_cvm}`} className="underline decoration-dotted">
            ← Companhia {cd_cvm}
          </a>
        </p>
        <h1 className="text-xl font-semibold">Arquivos originais</h1>
        <p className="text-sm text-tinta-suave max-w-2xl">
          O que a fonte publicou, guardado intacto. Baixe e rode{" "}
          <code className="font-mono text-xs">shasum -a 256</code> no arquivo: a
          saída tem de ser exatamente a digital abaixo. Se bater, o que está
          guardado aqui é byte a byte o que a fonte publicou.
        </p>
      </header>

      {capturas.length === 0 ? (
        <Vazio
          titulo="Nenhuma captura"
          dica="Nada foi ingerido ainda para as classes que esta chave lê."
        />
      ) : (
        <Tabela
          legenda="Arquivos capturados, com tamanho e digital SHA-256"
          colunas={["Arquivo", "Tamanho", "SHA-256", ""]}
        >
          {capturas.map((c) => (
            <tr key={c.id} className="border-b border-borda last:border-0">
              <th scope="row" className="text-left px-3 py-1.5">
                {c.nome_arquivo}
              </th>
              <td className="px-3 py-1.5 text-right tabular-nums text-sm">
                {bytes(c.tamanho_bytes)}
              </td>
              <td className="px-3 py-1.5">
                <code className="text-[11px] break-all">{c.sha256}</code>
              </td>
              <td className="px-3 py-1.5 whitespace-nowrap">
                <a
                  href={`/v1/capturas/${c.id}/arquivo`}
                  className="underline decoration-dotted text-sm"
                >
                  baixar
                </a>
              </td>
            </tr>
          ))}
        </Tabela>
      )}
    </div>
  );
}
