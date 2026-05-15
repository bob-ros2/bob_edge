---
name: web_researcher
description: Search the web and gather real-time information using SearXNG.
---

# Web Researcher Skill

This skill enables the agent to access the internet via a SearXNG instance. It is essential for retrieving current events, verifying facts, or researching technical documentation that is not part of the internal knowledge base.

## Usage
To use this skill, call **`execute_skill_script()`** with:
- **`skill_name`**: `"web_researcher"`
- **`script_path`**: `"scripts/search.py"`
- **`args`**: `"--query '<SEARCH_QUERY>' --num_results 5"`

## Best Practices
- Use specific queries for better results.
- For news, include keywords like "latest" or "today".
- Use `num_results` to control the depth of information (default is 3).

## Example
```json
execute_skill_script({
  "skill_name": "web_researcher",
  "script_path": "scripts/search.py",
  "args": "--query 'current ROS 2 humble release status' --num_results 3"
})
```
