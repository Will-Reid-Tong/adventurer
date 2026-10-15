# Adventurer

The choose-your-own-adventure engine. A single context covers the player
experience, the admin authoring tools, and the data model that ties them
together.

## Story graph

**Adventure**:
The whole story a player walks through: the set of all pages and the
options that link them.
_Avoid_: Story, branch, graph

**Page**:
One beat of an adventure. A page has a type (`choice`, `chance`, or
`ending`), a title, body text, and an optional image.
_Avoid_: Node, scene, step

**Start page**:
The page a player lands on when they begin an adventure. Configured in
admin settings; when unset, the first page by position is used.
_Avoid_: Entry point, root, landing page

**Option**:
A directed link from one page to another, ordered by `position`.
Choice-page options carry a `label` (the button text); chance-page
options carry a `weight`, and a chance page's weights must sum to
exactly 100.
_Avoid_: Choice, link, edge

**Choice page**:
A page whose options are presented to the player as labeled buttons;
clicking one navigates to that option's target.
_Avoid_: Decision page

**Chance page**:
A page where one Roll button triggers a server-side weighted pick from
its options. The chosen option's target page is shown next.
_Avoid_: Random page, dice page

**Ending page**:
A page with no options: a leaf in the adventure. The player UI shows a
Restart button that returns to the start page.
_Avoid_: Terminal page, leaf, end node

**Chance roll**:
The weighted draw on a chance page.
_Avoid_: Random draw, dice roll

## Authoring

**Adventure map**:
The admin's read-only visualization of an adventure's structure: pages
laid out top-down by depth from the start page, options drawn as
connectors between them.
_Avoid_: Branch map, graph view

**Reentrant edge**:
An option whose target sits at the same or shallower depth than its
source. Drawn dashed on the adventure map, since it points back up the
graph.
_Avoid_: Back edge, cycle edge

**Image**:
A JPEG, PNG, WebP, or GIF attached to a page, served at
`/images/<id>`.
_Avoid_: Asset, picture, attachment

**Admin**:
The single authenticated user who authors pages and options.
_Avoid_: Author, editor, operator
