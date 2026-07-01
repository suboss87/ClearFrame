# Docs

Supporting material for the ClearFrame take-home. Start with the main [README](../README.md)
for setup and architecture; the files here go deeper on specific angles.

| File | What it is |
|------|------------|
| [`SUBMISSION.md`](SUBMISSION.md) | The take-home write-up: the ask, what was built, how it maps to the evaluation criteria, and the demo script |
| [`Clearframe_Design_Doc.pdf`](Clearframe_Design_Doc.pdf) / [`design_doc.html`](design_doc.html) | The design document: problem framing, architecture, policy model, and scaling plan. The HTML is the editable source; the PDF is generated from it |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | How to deploy ClearFrame, a quick path (Vercel + Render) and a cloud-native path (AWS) |
| [`clearframe_logical_hld.excalidraw`](clearframe_logical_hld.excalidraw) | High-level architecture diagram: the perceive/decide split and the end-to-end data flow |
| [`clearframe_architecture.excalidraw`](clearframe_architecture.excalidraw) | Code-level architecture diagram: modules, files, and how they call each other |
| [`clearframe_aws_deployment.excalidraw`](clearframe_aws_deployment.excalidraw) | AWS deployment topology referenced in `DEPLOYMENT.md` |
| [`clearframe_simple_flow.excalidraw`](clearframe_simple_flow.excalidraw) | A minimal one-glance version of the flow, useful for opening a demo |

Diagrams are `.excalidraw` JSON, open them at [excalidraw.com](https://excalidraw.com) (Open) or the
VS Code Excalidraw extension.
