"""Widen embedding columns for real semantic vectors (TIP-014RE).

The 64-dimension columns were sized for the deterministic offline hash stub.
Real provider embeddings (OpenAI ``text-embedding-3-small``) are 1536-wide,
so ``chunks.embedding`` and ``file_chunks.embedding`` are widened in place:

* Existing 64-d vectors are zero-padded. Zero padding changes no pairwise
  cosine angle inside a generation, so ranking behaviour is IDENTICAL until
  the corpus is deliberately re-embedded; rows that ``answer_citations``
  reference are preserved, keeping the audit trail's FK integrity.
* ``search_generations.embedding_dimension`` moves from CHECK(=64) to a
  bounded range so historical hash generations (64) and provider
  generations (1536) coexist in the ledger. The constraint is located via
  the catalog rather than by guessed name.
* HNSW cosine indexes are rebuilt automatically by ALTER TYPE.

Operational note: after upgrading, run
``python -m rtr_copilot.commands.reembed_corpus`` so active generations are
re-embedded with the configured adapter (the generation fingerprint includes
embedding model + dimension, so re-embedding produces NEW generations and
atomically flips the active pointer — no in-place mutation).

Vector <-> array conversion goes through the text representation, which is
stable across pgvector versions.
"""

from alembic import op

revision = "0013_real_embedding_dim"
down_revision = "0012_enterprise_governance"
branch_labels = None
depends_on = None

NEW_DIMENSION = 1536
OLD_DIMENSION = 64

_DROP_DIMENSION_CHECKS = """
DO $$
DECLARE c record;
BEGIN
  FOR c IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'search_generations'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%embedding_dimension%'
  LOOP
    EXECUTE format(
      'ALTER TABLE search_generations DROP CONSTRAINT %I', c.conname
    );
  END LOOP;
END $$;
"""


def upgrade() -> None:
    pad = NEW_DIMENSION - OLD_DIMENSION
    for table in ("chunks", "file_chunks"):
        op.execute(f"""
        ALTER TABLE {table}
          ALTER COLUMN embedding TYPE vector({NEW_DIMENSION})
          USING (
            (
              string_to_array(
                trim(both '[]' from embedding::text), ','
              )::real[]
              || array_fill(0::real, ARRAY[{pad}])
            )::vector({NEW_DIMENSION})
          );
        """)
    op.execute(_DROP_DIMENSION_CHECKS)
    op.execute("""
    ALTER TABLE search_generations
      ADD CONSTRAINT search_generations_embedding_dimension_check
      CHECK (embedding_dimension BETWEEN 64 AND 3072);
    """)


def downgrade() -> None:
    # Slicing keeps the first 64 components. Hash-era vectors round-trip
    # exactly (their tail is the zero padding added above); provider vectors
    # are truncated and the corpus MUST be re-embedded after downgrading.
    # Dimension metadata is rewritten to match the post-slice reality so the
    # restored equality CHECK holds for every surviving row.
    for table in ("chunks", "file_chunks"):
        op.execute(f"""
        ALTER TABLE {table}
          ALTER COLUMN embedding TYPE vector({OLD_DIMENSION})
          USING (
            (
              string_to_array(
                trim(both '[]' from embedding::text), ','
              )::real[]
            )[1:{OLD_DIMENSION}]::vector({OLD_DIMENSION})
          );
        """)
    op.execute("""
    UPDATE search_generations SET embedding_dimension = 64
      WHERE embedding_dimension <> 64;
    """)
    op.execute(_DROP_DIMENSION_CHECKS)
    op.execute("""
    ALTER TABLE search_generations
      ADD CONSTRAINT search_generations_embedding_dimension_check
      CHECK (embedding_dimension = 64);
    """)
