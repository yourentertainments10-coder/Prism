# System Diagram

```text
                           PRISM
                             |
                     +-------+-------+
                     | User Interface|
                     +-------+-------+
                             |
                     +-------v-------+
                     | Request       |
                     | Classifier     |
                     +-------+-------+
                             |
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
     Deterministic      Specialized        Reasoning
        Engine             Engines           Engine
          |                  |                  |
     +----+----+       +-----+-----+       +---+---+
     |    |    |       |     |     |       |       |
   Math  Data  Code    Web   PDF   Media  Local   Cloud
   SQL   Files Build   APIs  OCR   FFmpeg Model   Models
     |    |    |       |     |     |       |       |
     +----+----+-------+-----+-----+-------+-------+
                             |
                     +-------v-------+
                     | Task Executor |
                     +-------+-------+
                             |
                     +-------v-------+
                     | Verification  |
                     +-------+-------+
                             |
                    +--------+--------+
                    |                 |
                   PASS              FAIL
                    |                 |
                    v                 v
                 Result          Diagnose/Fix
                                      |
                                      +----> Execute
```

The critical design choice is that the deterministic engine is a first-class
system, not merely a collection of tools attached to an LLM.
