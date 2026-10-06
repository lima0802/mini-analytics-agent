"""Wire the nodes into a LangGraph StateGraph.

START -> route --answer--> retrieve_context -> generate_sql -> validate --ok--> execute --ok--> synthesize -> END
           |                                       ^              |               |
           +--clarify / out_of_scope--+            +----error-----+-----error-----+   (max MAX_RETRIES retries)
                                      v                           |               |
                                   abstain <------- too many -----+---------------+
                                      |
                                     END
"""