---
name: mineru-document
description: Parse PDF, Office documents, and images with MinerU; optionally translate parsed Markdown and render a translated PDF. Use when the user asks to extract, understand, OCR, convert, or translate a document.
---

# MinerU Document

Use the MinerU MCP tools for document parsing and translation.

## Workflow

1. Use `mineru_parse_document` when the user needs structured Markdown or OCR output.
2. Use `mineru_translate_document` when the user wants a translated Markdown file and final translated PDF.
3. Pass an absolute local file path. Do not upload the file through chat attachments when a local path is already available.
4. Leave `add_to_library` enabled unless the user explicitly asks for temporary output.
5. Report the returned output paths and any PDF rendering warning.

The plugin uses the API address and Token configured in Plugin Management. Translation uses the global model selected in the plugin settings.
