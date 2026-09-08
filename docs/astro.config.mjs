// @ts-check
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import starlightSidebarTopics from "starlight-sidebar-topics";

const BASE = "/PSPixel";
const DOCS_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "src/content/docs");

// Astro (7.x) resolves relative links to sibling `.md` files, but drops the
// `#fragment` and leaves fragment-bearing links unresolved. Do the rewrite
// ourselves: `../foo.md#bar` -> `/PSPixel/foo/#bar`.
function rehypeDocLinks() {
  return (tree, file) => {
    const fromDir = dirname(file.path);
    const walk = (node) => {
      if (node.tagName === "a" && typeof node.properties?.href === "string") {
        const href = node.properties.href;
        const match = href.match(/^((?:\.\.?\/)?[\w./-]+)\.md(#.+)?$/);
        if (match && !/^https?:|^\//.test(href)) {
          let slug = relative(DOCS_ROOT, resolve(fromDir, `${match[1]}.md`))
            .replace(/\\/g, "/")
            .replace(/\.md$/, "")
            .replace(/(^|\/)index$/, "");
          node.properties.href = `${BASE}/${slug}/`.replace(/\/{2,}/g, "/") + (match[2] ?? "");
        }
      }
      for (const child of node.children ?? []) walk(child);
    };
    walk(tree);
  };
}

// https://astro.build/config
export default defineConfig({
  site: "https://psp515.github.io",
  base: BASE,
  markdown: { rehypePlugins: [rehypeDocLinks] },
  integrations: [
    starlight({
      title: "PSPixel",
      logo: { src: "./src/assets/logo.svg", alt: "PSPixel" },
      favicon: "/favicon.svg",
      customCss: ["./src/styles/custom.css"],
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/psp515/PSPixel",
        },
      ],
      plugins: [
        starlightSidebarTopics([
          {
            label: "User guide",
            link: "/setup/",
            icon: "open-book",
            items: [
              "setup",
              "web-installer",
              {
                label: "Channels",
                items: [
                  "channels",
                  "channels/network",
                  "channels/button",
                  "channels/mqtt",
                  "channels/webapi",
                ],
              },
              "animations",
            ],
          },
          {
            label: "Developer guide",
            link: "/development/",
            icon: "laptop",
            items: [
              "development",
              {
                label: "Contributing",
                items: [
                  "contributing",
                  "contributing/channels",
                  "contributing/animations",
                ],
              },
            ],
          },
        ]),
      ],
    }),
  ],
});
