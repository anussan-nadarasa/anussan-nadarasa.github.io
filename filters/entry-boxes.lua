--[[
entry-boxes.lua

For any page whose front matter has a `type:` field (i.e. an entry), adds:
  * a small type label and the "How AI was used" box at the top
  * an "Evidence" list and a link to the page's full git history at the bottom

Front matter it reads:

  type: project            # log | project | course | paper | reflection | essay
  evidence:
    - label: Code
      url: https://github.com/...
  ai:
    tools: [Claude Opus 5.5]
    did: What the AI did.
    me: What you did and how you checked it.
  # or simply:  ai: none
]]

local str = pandoc.utils.stringify

local function as_list(x)
  if x == nil then return {} end
  if pandoc.utils.type(x) == "List" then return x end
  return { x }
end

local function para(inlines_or_text)
  if type(inlines_or_text) == "string" then
    return pandoc.Para(pandoc.Inlines(inlines_or_text))
  end
  return pandoc.Para(inlines_or_text)
end

local function ai_box(ai)
  local blocks = pandoc.Blocks({})
  local t = pandoc.utils.type(ai)

  if t ~= "table" and t ~= "Meta" then
    -- scalar, e.g. "none"
    local s = str(ai)
    if s:lower() == "none" or s == "" then
      blocks:insert(para("No generative AI was used for this entry."))
    else
      blocks:insert(para(s))
    end
  else
    local tools = {}
    for _, v in ipairs(as_list(ai.tools)) do table.insert(tools, str(v)) end
    if #tools > 0 then
      blocks:insert(pandoc.Para({ pandoc.Strong("Tools: "), pandoc.Str(table.concat(tools, ", ")) }))
    end
    if ai.did then
      local p = pandoc.List({ pandoc.Strong("AI did: ") })
      p:extend(pandoc.utils.type(ai.did) == "Inlines" and ai.did or pandoc.Inlines(str(ai.did)))
      blocks:insert(pandoc.Para(p))
    end
    if ai.me then
      local p = pandoc.List({ pandoc.Strong("Author did and checked: ") })
      p:extend(pandoc.utils.type(ai.me) == "Inlines" and ai.me or pandoc.Inlines(str(ai.me)))
      blocks:insert(pandoc.Para(p))
    end
  end

  if quarto and quarto.Callout then
    return (quarto.Callout({ type = "note", title = "How AI was used", icon = false, content = blocks }))
  end
  return pandoc.Div(blocks, pandoc.Attr("", { "callout-note" }, { title = "How AI was used", icon = "false" }))
end

local function evidence_list(evidence)
  local items = {}
  for _, e in ipairs(as_list(evidence)) do
    if pandoc.utils.type(e) == "table" or pandoc.utils.type(e) == "Meta" then
      local label = e.label and str(e.label) or "Link"
      local url = e.url and str(e.url) or ""
      if url ~= "" then
        table.insert(items, { pandoc.Plain({ pandoc.Link(label, url) }) })
      end
    else
      local url = str(e)
      table.insert(items, { pandoc.Plain({ pandoc.Link(url, url) }) })
    end
  end
  if #items == 0 then return nil end
  return pandoc.Blocks({ pandoc.Header(2, "Evidence", pandoc.Attr("evidence")), pandoc.BulletList(items) })
end

local function relative_source_path()
  if not (quarto and quarto.doc and quarto.doc.input_file and quarto.project and quarto.project.directory) then
    return nil
  end
  local input, root = quarto.doc.input_file, quarto.project.directory
  if input:sub(1, #root) ~= root then return nil end
  local rel = input:sub(#root + 2)
  return (rel:gsub("\\", "/"))
end

function Pandoc(doc)
  local meta = doc.meta
  if not meta.type then return nil end -- not an entry

  local entry_type = str(meta.type)
  local top = pandoc.Blocks({
    pandoc.Div({ pandoc.Plain({ pandoc.Span(entry_type, pandoc.Attr("", { "entry-type" })) }) },
      pandoc.Attr("", { "entry-meta" })),
  })
  if meta.ai ~= nil then
    top:insert(ai_box(meta.ai))
  end

  local bottom = pandoc.Blocks({})
  local ev = evidence_list(meta.evidence)
  if ev then bottom:extend(ev) end

  local repo = meta["history-repo"] and str(meta["history-repo"]) or ""
  local branch = meta["history-branch"] and str(meta["history-branch"]) or "main"
  local rel = relative_source_path()
  if repo ~= "" and not repo:find("YOUR%-GITHUB%-USERNAME") and rel then
    bottom:insert(pandoc.Div({
      pandoc.Para({
        pandoc.Link("Revision history", repo .. "/commits/" .. branch .. "/" .. rel),
        pandoc.Str(" · "),
        pandoc.Link("Source", repo .. "/blob/" .. branch .. "/" .. rel),
      })
    }, pandoc.Attr("", { "entry-meta" })))
  end

  local blocks = pandoc.Blocks({})
  blocks:extend(top)
  blocks:extend(doc.blocks)
  blocks:extend(bottom)
  doc.blocks = blocks
  return doc
end
