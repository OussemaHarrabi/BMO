from neo4j import GraphDatabase

# Connect to Neo4j
driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", "password")  # replace if you set a different password
)

def create_schema(tx):
    # Create constraints for unique IDs
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (u:UserActivity) REQUIRE u.id IS UNIQUE")
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (f:File) REQUIRE f.id IS UNIQUE")
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (fo:Folder) REQUIRE fo.id IS UNIQUE")
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:ScreenCapture) REQUIRE s.id IS UNIQUE")
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (su:Summary) REQUIRE su.id IS UNIQUE")

    print("Constraints created.")

with driver.session() as session:
    session.execute_write(create_schema)

print("Neo4j schema setup complete!")
