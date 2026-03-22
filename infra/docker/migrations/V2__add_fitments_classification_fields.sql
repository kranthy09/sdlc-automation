-- V2: Add classification detail columns to fitments.
-- configuration_steps: JSONB array of config actions (PARTIAL_FIT).
-- dev_effort: t-shirt size S/M/L (GAP).
-- gap_type: gap categorisation (GAP).
-- config_steps / gap_description: LLM free-text already on ClassificationResult.
ALTER TABLE fitments ADD COLUMN IF NOT EXISTS config_steps TEXT;
ALTER TABLE fitments ADD COLUMN IF NOT EXISTS gap_description TEXT;
ALTER TABLE fitments ADD COLUMN IF NOT EXISTS configuration_steps JSONB;
ALTER TABLE fitments ADD COLUMN IF NOT EXISTS dev_effort TEXT;
ALTER TABLE fitments ADD COLUMN IF NOT EXISTS gap_type TEXT;
