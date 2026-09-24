// matte-vision — segmentação de pessoa em LOTE via Apple Vision.
//
//   matte-vision <dir-entrada> <dir-saida> [accurate|balanced|fast]
//
// Lê todos os .png de <dir-entrada> em ordem lexicográfica, roda
// VNGeneratePersonSegmentationRequest em cada um e grava, em <dir-saida>, um PNG
// CINZA de 8 bits com o MESMO nome — o canal alpha (0 = fundo, 255 = pessoa).
//
// Por que em lote, e não um frame por invocação: o modelo carrega uma vez.
// Medido nesta máquina (macOS 26.3, Swift 6.2.3, M-series): 144 ms no primeiro
// frame contra ~38 ms nos demais em .accurate. Uma invocação por frame pagaria
// os 144 ms toda vez.
//
// Zero dependência de terceiro: Vision faz parte do SO. Foi a razão da escolha
// (SPEC-03 §3.1) — a receita anterior morreu porque o pacote de terceiro sumiu
// da máquina e levou uma produção entregue junto.
//
// stdout: uma linha por frame — "<nome> <ms>"
// stderr: progresso e erros.

import Foundation
import Vision
import CoreImage
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

func morrer(_ msg: String) -> Never {
    FileHandle.standardError.write(("matte-vision: " + msg + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 3 else {
    morrer("uso: matte-vision <dir-entrada> <dir-saida> [accurate|balanced|fast]")
}
let dirEntrada = URL(fileURLWithPath: args[1], isDirectory: true)
let dirSaida = URL(fileURLWithPath: args[2], isDirectory: true)
let qualidadeArg = args.count >= 4 ? args[3] : "accurate"

let qualidade: VNGeneratePersonSegmentationRequest.QualityLevel
switch qualidadeArg {
case "accurate": qualidade = .accurate
case "balanced": qualidade = .balanced
case "fast":     qualidade = .fast
default: morrer("qualidade desconhecida: \(qualidadeArg) (accurate|balanced|fast)")
}

let fm = FileManager.default
try? fm.createDirectory(at: dirSaida, withIntermediateDirectories: true)

guard let nomes = try? fm.contentsOfDirectory(atPath: dirEntrada.path) else {
    morrer("não consegui listar \(dirEntrada.path)")
}
let entradas = nomes.filter { $0.lowercased().hasSuffix(".png") }.sorted()
guard !entradas.isEmpty else { morrer("nenhum .png em \(dirEntrada.path)") }

let request = VNGeneratePersonSegmentationRequest()
request.qualityLevel = qualidade
request.outputPixelFormat = kCVPixelFormatType_OneComponent8

// workingColorSpace nulo: a máscara é um canal, não é cor. Gerenciar cor aqui
// aplicaria uma curva de transferência no alpha e mudaria a borda.
let ctx = CIContext(options: [.workingColorSpace: NSNull()])
let cinza = CGColorSpaceCreateDeviceGray()
let handler = VNSequenceRequestHandler()

var feitos = 0
for nome in entradas {
    let src = dirEntrada.appendingPathComponent(nome)
    guard let isrc = CGImageSourceCreateWithURL(src as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(isrc, 0, nil) else {
        morrer("não consegui ler \(nome)")
    }
    let larg = img.width, alt = img.height

    let t0 = DispatchTime.now().uptimeNanoseconds
    do {
        try handler.perform([request], on: img)
    } catch {
        morrer("Vision falhou em \(nome): \(error)")
    }
    guard let obs = request.results?.first else {
        morrer("Vision não devolveu máscara para \(nome)")
    }
    let buf = obs.pixelBuffer
    let mw = CVPixelBufferGetWidth(buf), mh = CVPixelBufferGetHeight(buf)
    guard mw > 0 && mh > 0 else { morrer("máscara vazia em \(nome)") }

    // A máscara do Vision tem resolução própria (interna), não a da entrada.
    // Reescala pro extent da imagem de entrada — nunca pra um tamanho fixo.
    let ci = CIImage(cvPixelBuffer: buf)
    let escalada = ci.transformed(by: CGAffineTransform(scaleX: CGFloat(larg) / CGFloat(mw),
                                                        y: CGFloat(alt) / CGFloat(mh)))
    let alvo = CGRect(x: 0, y: 0, width: CGFloat(larg), height: CGFloat(alt))
    guard let saidaCG = ctx.createCGImage(escalada, from: alvo, format: .L8, colorSpace: cinza) else {
        morrer("não consegui rasterizar a máscara de \(nome)")
    }
    let ms = Double(DispatchTime.now().uptimeNanoseconds - t0) / 1_000_000.0

    let dst = dirSaida.appendingPathComponent(nome)
    guard let dest = CGImageDestinationCreateWithURL(dst as CFURL, UTType.png.identifier as CFString, 1, nil) else {
        morrer("não consegui criar \(dst.path)")
    }
    CGImageDestinationAddImage(dest, saidaCG, nil)
    guard CGImageDestinationFinalize(dest) else { morrer("falha ao gravar \(dst.path)") }

    print("\(nome) \(String(format: "%.1f", ms))")
    feitos += 1
    if feitos % 30 == 0 {
        FileHandle.standardError.write("  \(feitos)/\(entradas.count)\n".data(using: .utf8)!)
    }
}
FileHandle.standardError.write("  \(feitos)/\(entradas.count) máscaras\n".data(using: .utf8)!)
