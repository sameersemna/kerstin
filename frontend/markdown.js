// Small DOM-only Markdown subset for feedback (D017).
(function (root) {
  "use strict";

  const HEADING_RE = /^(#{1,})\s+(.*)$/;
  const LIST_RE = /^(\s*)([-*+]|\d+\.)\s+(.*)$/;
  const QUOTE_RE = /^\s*>\s?(.*)$/;
  const HR_RE = /^(?:-{3,}|\*{3,})$/;
  const WORD_RE = /[\p{L}\p{N}_]/u;

  function isWordChar(ch) {
    return ch !== undefined && WORD_RE.test(ch);
  }

  function flushText(spans, text) {
    if (text) spans.push({ type: "text", text });
  }

  function pushFormatted(spans, type, text) {
    for (const span of parseInline(text)) {
      spans.push(span.type === "text" ? { type, text: span.text } : span);
    }
  }

  function findClosing(input, marker, from, single) {
    let index = input.indexOf(marker, from);
    while (index !== -1) {
      const content = input.slice(from, index);
      const before = input[index - 1];
      const after = input[index + marker.length];
      if (
        content.length > 0 &&
        !/^\s/.test(content) &&
        !/\s$/.test(content) &&
        (after === undefined || !isWordChar(after)) &&
        (!single ||
          (before !== marker &&
            after !== marker &&
            !content.startsWith(marker) &&
            !content.endsWith(marker)))
      ) {
        return index;
      }
      index = input.indexOf(marker, index + 1);
    }
    return -1;
  }

  function parseInline(value) {
    const input = String(value == null ? "" : value);
    const spans = [];
    let text = "";
    let i = 0;

    while (i < input.length) {
      const ch = input[i];

      if (ch === "`") {
        const end = input.indexOf("`", i + 1);
        if (end > i + 1) {
          flushText(spans, text);
          text = "";
          spans.push({ type: "code", text: input.slice(i + 1, end) });
          i = end + 1;
          continue;
        }
      }

      if (ch === "*" || ch === "_") {
        const double = ch + ch;
        const strongStart =
          input.startsWith(double, i) &&
          (i === 0 || !isWordChar(input[i - 1])) &&
          !/^\s/.test(input.slice(i + 2));
        if (strongStart) {
          const end = findClosing(input, double, i + 2, false);
          if (end !== -1) {
            flushText(spans, text);
            text = "";
            pushFormatted(spans, "strong", input.slice(i + 2, end));
            i = end + 2;
            continue;
          }
        }

        const singleStart =
          input[i + 1] !== ch &&
          (i === 0 || input[i - 1] !== ch) &&
          (i === 0 || !isWordChar(input[i - 1])) &&
          !/^\s/.test(input.slice(i + 1));
        if (singleStart) {
          const end = findClosing(input, ch, i + 1, true);
          if (end !== -1) {
            flushText(spans, text);
            text = "";
            pushFormatted(spans, "em", input.slice(i + 1, end));
            i = end + 1;
            continue;
          }
        }
      }

      text += ch;
      i += 1;
    }

    flushText(spans, text);
    return spans;
  }

  function parseHeading(line) {
    const match = HEADING_RE.exec(line);
    if (!match) return null;
    return {
      type: "heading",
      level: Math.min(match[1].length, 4),
      inline: parseInline(match[2].trim()),
    };
  }

  function isHr(line) {
    return HR_RE.test(line.trim());
  }

  function matchListItem(line) {
    const match = LIST_RE.exec(line);
    if (!match) return null;
    return {
      indent: match[1].replace(/\t/g, "  ").length,
      ordered: /^\d+\.$/.test(match[2]),
      text: match[3],
    };
  }

  function parseList(lines, start, baseIndent, ordered, depth) {
    const rawItems = [];
    let i = start;

    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim() || HEADING_RE.test(line) || isHr(line) || QUOTE_RE.test(line)) {
        break;
      }

      const item = matchListItem(line);
      if (!item) {
        if (!rawItems.length) break;
        const indent = (line.match(/^\s*/) || [""])[0].replace(/\t/g, "  ").length;
        const last = rawItems[rawItems.length - 1];
        if (indent >= baseIndent + 2) {
          last.children.push({ type: "para", inline: parseInline(line.trim()) });
        } else {
          last.text += " " + line.trim();
        }
        i += 1;
        continue;
      }

      if (item.indent < baseIndent) break;
      if (item.ordered !== ordered && item.indent < baseIndent + 2) break;

      if (item.indent >= baseIndent + 2 && depth < 2 && rawItems.length) {
        const nested = parseList(lines, i, baseIndent + 2, item.ordered, depth + 1);
        rawItems[rawItems.length - 1].children.push(nested.block);
        i = nested.next;
        continue;
      }

      rawItems.push({ text: item.text, children: [] });
      i += 1;
    }

    return {
      block: {
        type: "list",
        ordered,
        items: rawItems.map((item) => ({
          inline: parseInline(item.text),
          children: item.children,
        })),
      },
      next: i,
    };
  }

  function parseMarkdown(value) {
    const input = String(value == null ? "" : value).replace(/\r\n?/g, "\n");
    if (!input.trim()) return [];

    const lines = input.split("\n").map((line) => line.replace(/[ \t]+$/, ""));
    const blocks = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) {
        i += 1;
        continue;
      }

      const heading = parseHeading(line);
      if (heading) {
        blocks.push(heading);
        i += 1;
        continue;
      }

      if (isHr(line)) {
        blocks.push({ type: "hr" });
        i += 1;
        continue;
      }

      if (QUOTE_RE.test(line)) {
        const parts = [];
        while (i < lines.length && QUOTE_RE.test(lines[i])) {
          parts.push(QUOTE_RE.exec(lines[i])[1]);
          i += 1;
        }
        blocks.push({ type: "quote", inline: parseInline(parts.join(" ")) });
        continue;
      }

      const listItem = matchListItem(line);
      if (listItem) {
        const list = parseList(lines, i, listItem.indent, listItem.ordered, 1);
        blocks.push(list.block);
        i = list.next;
        continue;
      }

      const parts = [];
      while (i < lines.length) {
        const current = lines[i];
        if (
          !current.trim() ||
          HEADING_RE.test(current) ||
          isHr(current) ||
          QUOTE_RE.test(current) ||
          matchListItem(current)
        ) {
          break;
        }
        parts.push(current.trim());
        i += 1;
      }
      blocks.push({ type: "para", inline: parseInline(parts.join(" ")) });
    }

    return blocks;
  }

  function appendInline(parent, spans, doc) {
    for (const span of spans) {
      if (span.type === "text") {
        parent.appendChild(doc.createTextNode(span.text));
        continue;
      }
      const tag = span.type === "strong" ? "strong" : span.type === "em" ? "em" : "code";
      const element = doc.createElement(tag);
      element.appendChild(doc.createTextNode(span.text));
      parent.appendChild(element);
    }
  }

  function appendBlock(parent, block, doc) {
    if (block.type === "heading") {
      const element = doc.createElement(block.level <= 2 ? "h3" : "h4");
      appendInline(element, block.inline, doc);
      parent.appendChild(element);
      return;
    }

    if (block.type === "list") {
      const element = doc.createElement(block.ordered ? "ol" : "ul");
      for (const item of block.items) {
        const li = doc.createElement("li");
        appendInline(li, item.inline, doc);
        for (const child of item.children) appendBlock(li, child, doc);
        element.appendChild(li);
      }
      parent.appendChild(element);
      return;
    }

    if (block.type === "quote") {
      const element = doc.createElement("blockquote");
      appendInline(element, block.inline, doc);
      parent.appendChild(element);
      return;
    }

    if (block.type === "hr") {
      parent.appendChild(doc.createElement("hr"));
      return;
    }

    if (block.type === "para") {
      const element = doc.createElement("p");
      appendInline(element, block.inline, doc);
      parent.appendChild(element);
      return;
    }

    throw new Error("unknown markdown block");
  }

  function renderMarkdown(value, doc = document) {
    try {
      const fragment = doc.createDocumentFragment();
      for (const block of parseMarkdown(value)) appendBlock(fragment, block, doc);
      return fragment;
    } catch {
      try {
        const fragment = doc.createDocumentFragment();
        const paragraph = doc.createElement("p");
        paragraph.appendChild(doc.createTextNode(String(value == null ? "" : value)));
        fragment.appendChild(paragraph);
        return fragment;
      } catch {
        return doc.createDocumentFragment();
      }
    }
  }

  root.parseMarkdown = parseMarkdown;
  root.renderMarkdown = renderMarkdown;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { parseMarkdown, renderMarkdown };
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
