-- Version-linked technical checks and actual media review are separate outcomes.
ALTER TABLE renders ADD COLUMN quality jsonb NOT NULL DEFAULT '{}';
