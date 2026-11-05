const test = require("node:test");
const assert = require("node:assert/strict");

const { parseMarkdown, renderMarkdown } = require("../markdown.js");

const SAMPLE = `### Was gut war
- Du hast **flüssig** erzählt.
- Gute Nebensätze mit *weil*.

### Wichtigste Fehler
- ❌ „Ich habe gestern in die Stadt gegangen.“
  - ✅ „Ich bin gestern in die Stadt gegangen.“
  - 💡 *gehen* forms the perfect with *sein*.

### Tipp für das nächste Gespräch
Benutze bewusst \`obwohl\`.`;

function fakeDocument() {
  const createdTags = [];
  const elements = [];
  let innerHTMLWrites = 0;

  function makeNode(tag) {
    const node = {
      tag,
      children: [],
      appendChild(child) {
        node.children.push(child);
        return child;
      },
    };
    Object.defineProperty(node, "innerHTML", {
      get() {
        return undefined;
      },
      set() {
        innerHTMLWrites += 1;
        throw new Error("innerHTML must not be set");
      },
    });
    return node;
  }

  return {
    createdTags,
    elements,
    get innerHTMLWrites() {
      return innerHTMLWrites;
    },
    createElement(tag) {
      createdTags.push(tag);
      const element = makeNode(tag);
      elements.push(element);
      return element;
    },
    createTextNode(text) {
      return {
        tag: "#text",
        text,
        children: [],
        appendChild(child) {
          this.children.push(child);
        },
      };
    },
    createDocumentFragment() {
      return makeNode("#fragment");
    },
  };
}

function tree(node) {
  if (node.tag === "#text") return node.text;
  return { tag: node.tag, children: node.children.map(tree) };
}

test("parses the real-shaped feedback sample", () => {
  assert.deepEqual(parseMarkdown(SAMPLE), [
    {
      type: "heading",
      level: 3,
      inline: [{ type: "text", text: "Was gut war" }],
    },
    {
      type: "list",
      ordered: false,
      items: [
        {
          inline: [
            { type: "text", text: "Du hast " },
            { type: "strong", text: "flüssig" },
            { type: "text", text: " erzählt." },
          ],
          children: [],
        },
        {
          inline: [
            { type: "text", text: "Gute Nebensätze mit " },
            { type: "em", text: "weil" },
            { type: "text", text: "." },
          ],
          children: [],
        },
      ],
    },
    {
      type: "heading",
      level: 3,
      inline: [{ type: "text", text: "Wichtigste Fehler" }],
    },
    {
      type: "list",
      ordered: false,
      items: [
        {
          inline: [
            {
              type: "text",
              text: "❌ „Ich habe gestern in die Stadt gegangen.“",
            },
          ],
          children: [
            {
              type: "list",
              ordered: false,
              items: [
                {
                  inline: [
                    {
                      type: "text",
                      text: "✅ „Ich bin gestern in die Stadt gegangen.“",
                    },
                  ],
                  children: [],
                },
                {
                  inline: [
                    { type: "text", text: "💡 " },
                    { type: "em", text: "gehen" },
                    { type: "text", text: " forms the perfect with " },
                    { type: "em", text: "sein" },
                    { type: "text", text: "." },
                  ],
                  children: [],
                },
              ],
            },
          ],
        },
      ],
    },
    {
      type: "heading",
      level: 3,
      inline: [{ type: "text", text: "Tipp für das nächste Gespräch" }],
    },
    {
      type: "para",
      inline: [
        { type: "text", text: "Benutze bewusst " },
        { type: "code", text: "obwohl" },
        { type: "text", text: "." },
      ],
    },
  ]);
});

test("nests lists one level and flattens deeper levels", () => {
  assert.deepEqual(parseMarkdown("- eins\n  - zwei\n    - drei\n      - vier"), [
    {
      type: "list",
      ordered: false,
      items: [
        {
          inline: [{ type: "text", text: "eins" }],
          children: [
            {
              type: "list",
              ordered: false,
              items: [
                { inline: [{ type: "text", text: "zwei" }], children: [] },
                { inline: [{ type: "text", text: "drei" }], children: [] },
                { inline: [{ type: "text", text: "vier" }], children: [] },
              ],
            },
          ],
        },
      ],
    },
  ]);
});

test("parses ordered lists", () => {
  assert.deepEqual(parseMarkdown("1. eins\n2. zwei"), [
    {
      type: "list",
      ordered: true,
      items: [
        { inline: [{ type: "text", text: "eins" }], children: [] },
        { inline: [{ type: "text", text: "zwei" }], children: [] },
      ],
    },
  ]);
});

test("appends a continuation line to the previous item", () => {
  assert.deepEqual(parseMarkdown("- Erster Satz\nfortsetzung mit **fett**"), [
    {
      type: "list",
      ordered: false,
      items: [
        {
          inline: [
            { type: "text", text: "Erster Satz fortsetzung mit " },
            { type: "strong", text: "fett" },
          ],
          children: [],
        },
      ],
    },
  ]);
});

test("turns indented correction lines into child paragraphs", () => {
  assert.deepEqual(
    parseMarkdown("- ❌ Original: *falsch*\n  ✅ Korrektur: *richtig*\n  💡 Erklärung."),
    [
      {
        type: "list",
        ordered: false,
        items: [
          {
            inline: [
              { type: "text", text: "❌ Original: " },
              { type: "em", text: "falsch" },
            ],
            children: [
              {
                type: "para",
                inline: [
                  { type: "text", text: "✅ Korrektur: " },
                  { type: "em", text: "richtig" },
                ],
              },
              {
                type: "para",
                inline: [{ type: "text", text: "💡 Erklärung." }],
              },
            ],
          },
        ],
      },
    ]
  );
});

test("keeps underscore words and multiplication text", () => {
  assert.deepEqual(parseMarkdown("snake_case_word und 2*3*4"), [
    {
      type: "para",
      inline: [{ type: "text", text: "snake_case_word und 2*3*4" }],
    },
  ]);
});

test("keeps an unmatched strong marker literal", () => {
  assert.deepEqual(parseMarkdown("**offen"), [
    { type: "para", inline: [{ type: "text", text: "**offen" }] },
  ]);
});

test("parses the server's italic empty-feedback text", () => {
  assert.deepEqual(parseMarkdown("_Noch keine Äußerungen._"), [
    { type: "para", inline: [{ type: "em", text: "Noch keine Äußerungen." }] },
  ]);
});

test("flattens nested emphasis without leaving markers visible", () => {
  assert.deepEqual(
    parseMarkdown("*Ich wohne seit zwei **Jahren** in Berlin*"),
    [
      {
        type: "para",
        inline: [
          { type: "em", text: "Ich wohne seit zwei " },
          { type: "strong", text: "Jahren" },
          { type: "em", text: " in Berlin" },
        ],
      },
    ]
  );
});

test("handles CRLF and empty input", () => {
  assert.deepEqual(parseMarkdown("### Titel\r\n- eins\r\n- zwei"), [
    {
      type: "heading",
      level: 3,
      inline: [{ type: "text", text: "Titel" }],
    },
    {
      type: "list",
      ordered: false,
      items: [
        { inline: [{ type: "text", text: "eins" }], children: [] },
        { inline: [{ type: "text", text: "zwei" }], children: [] },
      ],
    },
  ]);
  assert.deepEqual(parseMarkdown(""), []);
});

test("parses quotes, rules and heading levels", () => {
  assert.deepEqual(parseMarkdown("> Zitat\n> weiter\n\n---"), [
    { type: "quote", inline: [{ type: "text", text: "Zitat weiter" }] },
    { type: "hr" },
  ]);
  assert.deepEqual(parseMarkdown("## zwei\n#### vier\n##### fünf"), [
    {
      type: "heading",
      level: 2,
      inline: [{ type: "text", text: "zwei" }],
    },
    {
      type: "heading",
      level: 4,
      inline: [{ type: "text", text: "vier" }],
    },
    {
      type: "heading",
      level: 4,
      inline: [{ type: "text", text: "fünf" }],
    },
  ]);
});

test("keeps HTML, links and images as text spans", () => {
  const unsafe = [
    "<img src=x onerror=alert(1)>",
    "<script>alert(1)</script>",
    "[x](javascript:alert(1))",
    "![a](http://x/y.png)",
  ];

  for (const input of unsafe) {
    const blocks = parseMarkdown(input);
    assert.equal(blocks.length, 1);
    assert.equal(blocks[0].type, "para");
    assert.ok(blocks[0].inline.every((span) => span.type === "text"));
    assert.equal(
      blocks[0].inline.map((span) => span.text).join(""),
      input
    );
  }
});

test("renders the sample as an allowed DOM tree", () => {
  const doc = fakeDocument();
  const root = renderMarkdown(SAMPLE, doc);

  assert.deepEqual(tree(root), {
    tag: "#fragment",
    children: [
      {
        tag: "h4",
        children: ["Was gut war"],
      },
      {
        tag: "ul",
        children: [
          {
            tag: "li",
            children: [
              "Du hast ",
              { tag: "strong", children: ["flüssig"] },
              " erzählt.",
            ],
          },
          {
            tag: "li",
            children: [
              "Gute Nebensätze mit ",
              { tag: "em", children: ["weil"] },
              ".",
            ],
          },
        ],
      },
      {
        tag: "h4",
        children: ["Wichtigste Fehler"],
      },
      {
        tag: "ul",
        children: [
          {
            tag: "li",
            children: [
              "❌ „Ich habe gestern in die Stadt gegangen.“",
              {
                tag: "ul",
                children: [
                  {
                    tag: "li",
                    children: ["✅ „Ich bin gestern in die Stadt gegangen.“"],
                  },
                  {
                    tag: "li",
                    children: [
                      "💡 ",
                      { tag: "em", children: ["gehen"] },
                      " forms the perfect with ",
                      { tag: "em", children: ["sein"] },
                      ".",
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
      {
        tag: "h4",
        children: ["Tipp für das nächste Gespräch"],
      },
      {
        tag: "p",
        children: [
          "Benutze bewusst ",
          { tag: "code", children: ["obwohl"] },
          ".",
        ],
      },
    ],
  });

  const allowed = new Set([
    "h3",
    "h4",
    "ul",
    "ol",
    "li",
    "blockquote",
    "hr",
    "p",
    "strong",
    "em",
    "code",
  ]);
  for (const tag of doc.createdTags) assert.ok(allowed.has(tag), `unexpected tag ${tag}`);
  for (const element of doc.elements) {
    assert.equal(Object.hasOwn(element, "href"), false);
    assert.equal(Object.hasOwn(element, "src"), false);
    for (const key of Object.getOwnPropertyNames(element)) {
      assert.ok(!/^on/i.test(key), `unexpected property ${key}`);
    }
  }
  assert.equal(doc.innerHTMLWrites, 0);
});

test("renders heading levels as h3/h4 and unsafe text as paragraphs", () => {
  const doc = fakeDocument();
  renderMarkdown("## zwei\n#### vier\n\n<img src=x onerror=alert(1)>", doc);

  assert.deepEqual(doc.createdTags, ["h3", "h4", "p"]);
  assert.equal(doc.innerHTMLWrites, 0);
});
