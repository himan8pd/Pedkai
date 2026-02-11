# Pedkai Project Constraints

This document defines the operational constraints for AI agents and collaborators working on the Pedkai project.

## 1. Artifact Management
- **Centralized Synchronization**: All project artifacts (Task Lists, Walkthroughs, Strategic Reviews, Implementation Plans) must be maintained in the **main project directory** (`/Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My Drive/AI Learning/AntiGravity/Pedkai`).
- **Primary Source of Truth**: Artifacts in the project root are the primary source of truth. Any internal "brain" directory state must be synchronized to the root after any modifications.
- **Naming Conventions**:
    - `task.md`: Latest project status and roadmap.
    - `walkthrough.md`: Proof of implementation and verification.
    - `implementation_plan_consolidated.md`: Unified history of technical implementation.

## 2. Security & Compliance
- **No Hardcoded Secrets**: Credentials must always be environment-injected.
- **TMF Compliance**: All new API surface area must follow TM Forum OpenAPI standards where applicable.
- **RBAC**: All endpoints must be secured with appropriate role-based access control scopes.
