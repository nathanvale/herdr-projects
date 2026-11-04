# Shepherdr task delivery

The language used to describe task work, forge operations, and completion.

## Language

### Forge work

**Forge**:
The hosting provider that owns a repository's pull requests, checks, and review activity, such as GitHub or Bitbucket Cloud.

**Forge adapter**:
Shepherdr's provider-specific interpretation of repository identity, pull requests, publication, checks, and feedback.

**Repository identity**:
The forge, host, and repository that distinguish the remote repository associated with a task. A connection alias or repository name alone does not establish this identity.

**Pull request identity**:
The repository-qualified identity of a pull request, including its number and verified link. Equal numbers in different repositories identify different pull requests.
_Avoid_: PR number, when referring to the complete identity.

**Candidate**:
The exact task commit proposed for review and integration.
_Avoid_: Latest code, source branch.

**Source branch**:
The branch supplying a pull request's proposed changes. Its current commit can change without changing the branch's identity.
_Avoid_: Candidate, when referring to the branch.

**Destination**:
The repository and branch selected to receive a candidate's changes.
_Avoid_: Main, unless the selected branch is actually named main.

**Publication**:
Establishment of the task's pull request with its source, destination, and candidate confirmed. A published pull request may still be a draft.

**Uncertain publication**:
A publication attempt whose remote outcome has not been established. A missing reply or empty lookup alone does not prove that no pull request was created.

### Review and integration

**Readiness**:
A task's declaration that an exact candidate is ready for the next integration decision. Readiness does not establish approval or integration.

**Check observation**:
The reported checks for an exact candidate, including their outcomes and whether the results are complete. Missing, incomplete, pending, failed, and passed observations have different meanings.

**Approval evidence**:
The candidate-specific changes, check observations, and proof presented for an integration decision.
_Avoid_: Integration evidence, when referring only to support for a decision.

**Integration**:
The confirmed inclusion of the approved task work in its destination. A submitted merge request is not yet confirmed integration.

**External merge evidence**:
Verified observations connecting an externally merged pull request to its repository, source candidate, destination, and merge commit in fetched destination history.

### Task completion

**Task**:
A bounded assignment with its own brief, conversation, and work. Its history remains identifiable after its execution resources are removed.

**Dependency**:
A predecessor task whose workflow release condition must be satisfied before a queued task proceeds. Satisfying a dependency does not establish code availability or authorize merge or deployment.

**Hold**:
A condition that prevents a task action from proceeding safely.

**Base synchronization**:
Alignment of the local destination checkout with confirmed destination history while preserving local work.

**Completion**:
The concluding workflow for a task, with integration where applicable, base synchronization, and cleanup treated as distinct outcomes.

**Cleanup**:
Removal of the task's safely removable owned execution resources while retaining its history and evidence. Integration and cleanup are separate outcomes.

**Cleanup pending**:
Cleanup whose required work or confirmation remains outstanding.

**Cleanup held**:
Cleanup that retains resources because a condition prevents safe removal.

**Cleanup complete**:
Successful conclusion of task cleanup, with every required removal confirmed and no unresolved cleanup hold.

**Resource ownership**:
The established relationship between a task and the particular resources used for its execution. Ownership distinguishes those resources from replacements and resources belonging to other work.

**Conversation**:
The retained exchange between a task's human participants and agents, including its brief and subsequent messages.

### Authentication and execution

**Execution host**:
The machine on which a repository's operations run. It can differ from the application host.
_Avoid_: Server, local machine.

**Application host**:
The machine running Shepherdr and holding its application state.
_Avoid_: Execution host, repository host.

**Host-managed authentication**:
Authentication established through the execution host's existing tools and account setup.
_Avoid_: Shepherdr credentials, agent grant.

**Secret vault**:
Shepherdr's collection of named secrets available to agents within a human-selected scope.
_Avoid_: Host authentication, agent grant.

**Agent grant**:
The authority assigned to one agent session to perform specified Shepherdr actions.
_Avoid_: Account credential, forge token.

**Regular repository**:
A repository whose operations have no retained containment restrictions.
_Avoid_: Trusted repository, regular-mode space.

**Contained repository**:
A repository whose operations remain subject to restrictions arising from contained execution, including after that execution ends.
_Avoid_: Active sandbox, contained-mode label.

**Checked repository broker**:
The controlled route for repository operations that enforces containment restrictions.
_Avoid_: Core transport, unrestricted host execution.
