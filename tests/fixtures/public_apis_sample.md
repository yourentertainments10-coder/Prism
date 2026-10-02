## APILayer APIs
| API | Description | Call this API |
|---|---|---|
| [Highlight](https://highlight.example) | Not a catalogue row | [Run](https://postman.example) |

## MCP Servers
| Name | Description | Auth | Transport | Install |
|---|---|---|---|---|
| [MCP item](https://mcp.example) | Not an API row | No | `stdio` | [Install](https://install.example) |

### Books
API | Description | Auth | HTTPS | CORS |
|:---|:---|:---|:---|:---|
| [Same Name](https://books.example/one) | Book lookup service | `apiKey` | Yes | Unknown |
| [Same Name](https://books.example/two) | Another book lookup | OAuth | Yes | No |
| [Recoverable](https://recover.example) | Extra source cell | No | Yes | Yes | source note |
| [Malformed](https://malformed.example) | Missing columns | No | Yes |

### Science
| API | Description | Auth | HTTPS | CORS |
|---|:---|:---|:---|:---|
| [Same Name](https://books.example/one) | Same listing in another category | No | No | Unknown |
