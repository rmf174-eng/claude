// rosto-vision — linha dos olhos, por frame, via Apple Vision.
//
//   rosto-vision <dir-entrada>
//
// Lê os .png de <dir-entrada> em ordem lexicográfica e, para cada um, escreve
// UMA linha no stdout:
//
//   <nome> <cx> <cy> <largura> <confianca>     — rosto achado
//   <nome> - - - -                              — nenhum rosto neste frame
//
// `cx`/`cy` são a LINHA DOS OLHOS normalizada em 0..1, com a origem no CANTO
// SUPERIOR ESQUERDO (Vision devolve com origem embaixo; a conversão é aqui, uma
// vez, e não em cada consumidor).
//
// ── POR QUE VISION, E NÃO O HAAR CASCADE ────────────────────────────────────
// A referência que inspirou este pré-passo usa `haarcascade_frontalface_default`
// do OpenCV. Duas razões para não seguir:
//   1. OpenCV é ~90 MB de dependência nova, e pode não estar instalado — num
//      repo cuja regra é não depender do que pode sumir (SPEC-03 §3.1: uma
//      receita já morreu exatamente assim).
//   2. Haar é frontal e de 2001: rosto de perfil, inclinado ou com metade fora
//      do quadro simplesmente não é detectado, e num talking-head de mão solta
//      isso é metade da peça.
// Vision faz parte do SO, detecta rosto em perfil e devolve LANDMARKS — os
// olhos de verdade, não uma estimativa.
//
// ── O MECANISMO QUE VALE COPIAR ─────────────────────────────────────────────
// O insight da referência não é o detector, é ANCORAR NOS OLHOS e não no centro
// do rosto: enquadrar pelo centro deixa o olhar alto demais no quadro. Eles
// estimam a linha dos olhos a 42% da altura da caixa. Nós usamos os landmarks
// quando existem e caímos nos 42% quando não — mesma âncora, medida em vez de
// estimada.
//
// Zero dependência de terceiro. Em lote pelo mesmo motivo do matte-vision: o
// modelo carrega uma vez.

import Foundation
import Vision
import CoreImage
import CoreGraphics
import ImageIO

func morrer(_ msg: String) -> Never {
    FileHandle.standardError.write(("rosto-vision: " + msg + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 2 else { morrer("uso: rosto-vision <dir-entrada>") }
let dirEntrada = URL(fileURLWithPath: args[1], isDirectory: true)

let fm = FileManager.default
guard let itens = try? fm.contentsOfDirectory(at: dirEntrada,
                                              includingPropertiesForKeys: nil) else {
    morrer("não consigo ler \(dirEntrada.path)")
}
let pngs = itens.filter { $0.pathExtension.lowercased() == "png" }
                .sorted { $0.lastPathComponent < $1.lastPathComponent }
guard !pngs.isEmpty else { morrer("nenhum .png em \(dirEntrada.path)") }

FileHandle.standardError.write("rosto-vision: \(pngs.count) frame(s)\n".data(using: .utf8)!)

// 42% da altura da caixa — o fallback quando não há landmark de olho. É o mesmo
// número da referência, e é uma boa estimativa: o olho humano fica acima do
// meio do rosto, não no meio.
let FRACAO_OLHOS = 0.42

var achados = 0
for (i, url) in pngs.enumerated() {
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        print("\(url.lastPathComponent) - - - -")
        continue
    }
    let req = VNDetectFaceLandmarksRequest()
    let handler = VNImageRequestHandler(cgImage: img, options: [:])
    do { try handler.perform([req]) } catch {
        print("\(url.lastPathComponent) - - - -")
        continue
    }
    guard let obs = (req.results ?? []).max(by: {
        $0.boundingBox.width * $0.boundingBox.height
            < $1.boundingBox.width * $1.boundingBox.height
    }) else {
        print("\(url.lastPathComponent) - - - -")
        continue
    }
    achados += 1
    let bb = obs.boundingBox            // origem no canto INFERIOR esquerdo
    var cx = bb.midX
    // fallback: 42% da altura, contado do TOPO da caixa
    var cy = 1.0 - (bb.maxY - bb.height * FRACAO_OLHOS)

    // Landmarks, quando existem: a média dos dois olhos é a âncora medida.
    if let lm = obs.landmarks,
       let e1 = lm.leftEye?.normalizedPoints,
       let e2 = lm.rightEye?.normalizedPoints,
       !e1.isEmpty, !e2.isEmpty {
        // normalizedPoints são relativos à CAIXA, não ao quadro.
        let m1x = e1.reduce(0.0) { $0 + Double($1.x) } / Double(e1.count)
        let m1y = e1.reduce(0.0) { $0 + Double($1.y) } / Double(e1.count)
        let m2x = e2.reduce(0.0) { $0 + Double($1.x) } / Double(e2.count)
        let m2y = e2.reduce(0.0) { $0 + Double($1.y) } / Double(e2.count)
        let ex = (m1x + m2x) / 2.0
        let ey = (m1y + m2y) / 2.0
        cx = bb.minX + ex * bb.width
        cy = 1.0 - (bb.minY + ey * bb.height)
    }
    print(String(format: "%@ %.5f %.5f %.5f %.3f", url.lastPathComponent,
                 cx, cy, bb.width, obs.confidence))
    if (i + 1) % 50 == 0 {
        FileHandle.standardError.write("  \(i + 1)/\(pngs.count)\n".data(using: .utf8)!)
    }
}
FileHandle.standardError.write(
    "rosto-vision: \(achados)/\(pngs.count) frame(s) com rosto\n".data(using: .utf8)!)
