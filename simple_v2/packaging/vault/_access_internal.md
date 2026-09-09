---
type: frontmatter-patch
include:
  - "roles/**"
  - "state/**"
priority: 0
---

Роли и служебное состояние — внутреннее, круг `agent_internal`.

Патч живёт в корне волта, а не внутри `roles/`. Fleet считает ролью всякую
заметку в этой папке, поэтому патч, положенный туда, заставляет флот ругаться
на «роль без fleet_id» на каждом опросе.

```jsonnet
{ subgraphs: ["agent_internal"] }
```
