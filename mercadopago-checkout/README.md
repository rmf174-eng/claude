# Checkout Mercado Pago (Checkout Pro) — Node.js + TypeScript

Venda de produto único: o cliente clica em pagar, é redirecionado ao Mercado Pago
(Pix, cartão, boleto, saldo) e o servidor confirma o pagamento por **webhook**.

## Por que Checkout Pro
Menor esforço e risco: o Mercado Pago coleta os dados do cartão (você fica fora do escopo PCI),
já oferece Pix/boleto/parcelamento e a conversão é validada. Migre para Bricks só se precisar
do formulário dentro do seu site.

## Passo a passo
1. **Crie a aplicação**: https://www.mercadopago.com.br/developers/panel/app → *Criar aplicação* → produto *Checkout Pro*.
2. **Credenciais de teste**: copie o *Access Token* de teste para `.env` (`cp .env.example .env`).
3. **Rode**: `npm run dev`.
4. **URL pública** (o webhook precisa alcançar seu servidor): `cloudflared tunnel --url http://localhost:3000` ou `ngrok http 3000`; coloque a URL em `BASE_URL`.
5. **Webhook**: painel → *Webhooks* → URL `BASE_URL/webhooks/mercadopago`, evento **Pagamentos**. Copie a *chave secreta* para `MP_WEBHOOK_SECRET`.
6. **Teste** com usuários/cartões de teste: https://www.mercadopago.com.br/developers/pt/docs/checkout-pro/integration-test
7. **Produção**: troque pelo Access Token de produção (aplicação homologada), use HTTPS e um banco de dados no lugar do `Map` em memória.

## Segurança (já implementado)
- Preço definido no servidor (`PRODUCTS`), nunca enviado pelo navegador.
- Assinatura `x-signature` validada com HMAC-SHA256 (`src/signature.ts`, testado).
- O pagamento é reconsultado na API do Mercado Pago; o corpo do webhook não é confiado.
- Idempotência: notificações repetidas não entregam o produto duas vezes.
- Nunca versione o `.env`; o Access Token é secreto.

## Onde entregar o produto
`src/server.ts`, no ramo `payment.status === "approved"` (log "liberar acesso").
