# Tmux Cheat Sheet: Kafka Management Edition

## 1. Essential Session Management
*From your main terminal prompt (SSH).*


| Task | Command |
| :--- | :--- |
| **List all sessions** | `tmux ls` |
| **Attach to Kafka Replay** | `tmux attach -t kafka-replay` |
| **Attach to Kafka Consumer** | `tmux attach -t kafka-consumer+abeyance-memory-update` |
| **New named session** | `tmux new -s <name>` |
| **Rename existing session** | `tmux rename-session -t <old_name> <new_name>` |
| **Kill/Stop a session** | `tmux kill-session -t <name>` |

---

## 2. Inside the Session (The "Hotkeys")
*Press **Ctrl + b**, release, then hit the key.*


| Action | Key Combination |
| :--- | :--- |
| **Detach** (Go to main prompt) | `d` |
| **Rename** current session | `,` (comma) |
| **Switch** sessions (List view) | `s` |
| **Scroll Mode** (Arrows/PgUp) | `[` (Press `q` to exit) |
| **Zoom Pane** (Full screen) | `z` |
| **Split Horizontally** | `"` |
| **Split Vertically** | `%` |

---

## 3. Background Process & Log Management
*Best practices for your Kafka jobs.*

*   **Run command in background:** 
    `nohup ./your_script.sh > output.log 2>&1 &`
*   **Watch log live:** 
    `tail -f output.log` (Use `Ctrl + C` to stop watching; the process continues).
*   **Find a hidden PID:** 
    `ps aux | grep kafka`

---

## 4. Stability Warnings
*   **Docker Restart:** Restarting `docker.service` kills containers inside tmux sessions unless a restart policy is set.
*   **System Prompt:** Avoid restarting `user@1001.service` or `systemd-logind` until Kafka jobs finish.
*   **Reboot:** All tmux sessions are wiped on reboot. Use a tool like [tmux-resurrect](https://github.com) to save sessions across reboots.
