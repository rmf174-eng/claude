import "dotenv/config";
import express from "express";
import { MercadoPagoConfig, Payment, Preference } from "mercadopago";
import { randomUUID } from "node:crypto";
import { isValidSignature } from "./signature.js";

const { MP_ACCESS_TOKEN, MP_WEBHOOK_SECRET, BASE_URL, PORT = "3000" } = process.env;
if (!MP_ACCESS_TOKEN || !BASE_URL) {
  throw new Error("Defina MP_ACCESS_TOKEN e BASE_URL no .env (veja .env.example)");
}

const mp = new MercadoPagoConfig({ accessToken: MP_ACCESS_TOKEN });

// Catálogo no servidor: o preço NUNCA vem do navegador.
const PRODUCTS: Record<string, { title: string; price: number }> = {
  "produto-1": { title: "Meu Produto", price: 97.0 },
};

// Troque por banco de dados (Postgres, etc.). Em memória só para o exemplo.
type Order = { id: string; productId: string; status: "pending" | "paid" | "failed"; paymentId?: string };
const orders = new Map<string, Order>();

const app = express();
app.use(express.json());
app.use(express.static("public"));

// 1) Cria o pedido e a preferência do Checkout Pro; devolve a URL de pagamento.
app.post("/api/checkout", async (req, res) => {
  const product = PRODUCTS[String(req.body?.productId)];
  if (!product) return res.status(400).json({ error: "Produto inválido" });

  const order: Order = { id: randomUUID(), productId: req.body.productId, status: "pending" };
  orders.set(order.id, order);

  try {
    const pref = await new Preference(mp).create({
      body: {
        items: [{ id: order.productId, title: product.title, quantity: 1, unit_price: product.price, currency_id: "BRL" }],
        external_reference: order.id, // volta no webhook para ligar pagamento -> pedido
        back_urls: {
          success: `${BASE_URL}/resultado.html?status=success`,
          pending: `${BASE_URL}/resultado.html?status=pending`,
          failure: `${BASE_URL}/resultado.html?status=failure`,
        },
        auto_return: "approved",
        notification_url: `${BASE_URL}/webhooks/mercadopago`,
      },
    });
    res.json({ orderId: order.id, checkoutUrl: pref.init_point, sandboxUrl: pref.sandbox_init_point });
  } catch (err) {
    console.error("Erro ao criar preferência", err);
    res.status(502).json({ error: "Falha ao criar o checkout" });
  }
});

// 2) Webhook: valida assinatura, consulta o pagamento na API e atualiza o pedido.
app.post("/webhooks/mercadopago", async (req, res) => {
  const dataId = String(req.query["data.id"] ?? req.body?.data?.id ?? "");

  if (MP_WEBHOOK_SECRET) {
    const ok = isValidSignature({
      secret: MP_WEBHOOK_SECRET,
      xSignature: req.header("x-signature"),
      xRequestId: req.header("x-request-id"),
      dataId: String(req.query["data.id"] ?? ""),
    });
    if (!ok) return res.sendStatus(401);
  } else {
    console.warn("MP_WEBHOOK_SECRET ausente: assinatura NÃO validada (não use em produção)");
  }

  // Só nos interessa o tópico de pagamento; responda 200 rápido aos demais.
  if ((req.body?.type ?? req.query.type) !== "payment" || !dataId) return res.sendStatus(200);

  try {
    // Nunca confie no corpo da notificação: busque o estado real na API.
    const payment = await new Payment(mp).get({ id: dataId });
    const order = payment.external_reference ? orders.get(payment.external_reference) : undefined;
    if (!order) return res.sendStatus(200);

    if (order.paymentId === dataId && order.status === "paid") return res.sendStatus(200); // idempotência

    if (payment.status === "approved") {
      order.status = "paid";
      order.paymentId = dataId;
      console.log(`Pedido ${order.id} pago (pagamento ${dataId}) -> liberar acesso/entregar produto aqui`);
    } else if (payment.status === "rejected" || payment.status === "cancelled") {
      order.status = "failed";
    }
    res.sendStatus(200);
  } catch (err) {
    console.error("Erro no webhook", err);
    res.sendStatus(500); // o Mercado Pago reenvia
  }
});

app.get("/api/orders/:id", (req, res) => {
  const order = orders.get(req.params.id);
  order ? res.json({ id: order.id, status: order.status }) : res.sendStatus(404);
});

app.listen(Number(PORT), () => console.log(`Servidor em http://localhost:${PORT}`));
