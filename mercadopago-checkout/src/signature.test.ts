import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { isValidSignature } from "./signature.js";

const secret = "segredo";
const sign = (id: string, req: string, ts: string) =>
  createHmac("sha256", secret).update(`id:${id};request-id:${req};ts:${ts};`).digest("hex");

test("aceita assinatura válida", () => {
  const v1 = sign("123", "req-1", "1700000000");
  assert.ok(isValidSignature({ secret, xSignature: `ts=1700000000,v1=${v1}`, xRequestId: "req-1", dataId: "123" }));
});

test("rejeita assinatura adulterada ou ausente", () => {
  assert.equal(isValidSignature({ secret, xSignature: "ts=1,v1=abc", xRequestId: "req-1", dataId: "123" }), false);
  assert.equal(isValidSignature({ secret, xSignature: undefined, xRequestId: "r", dataId: "1" }), false);
});
