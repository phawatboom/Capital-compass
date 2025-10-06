library(readxl)
library(tidyverse)

path <- "MXUS_data.xlsx"   # adjust if needed
raw  <- readxl::read_excel(path, col_names = FALSE, sheet = "Returns")

# Find the header row where first column literally equals "Date"
date_row <- which(trimws(as.character(raw[[1]])) == "Date")
stopifnot(length(date_row) == 1)

hdr <- as.character(unlist(raw[date_row, ]))
dat <- raw[(date_row + 1):nrow(raw), , drop = FALSE]
colnames(dat) <- hdr

# Keep Date + stock columns, coerce returns to numeric
# Keep Date + stock columns, coerce returns to numeric (but NOT Date)
returns_df <- dat %>%
  select(where(~ !all(is.na(.x)))) %>%
  mutate(Date = as.Date(as.numeric(Date), origin = "1899-12-30")) %>%
  mutate(across(-Date, ~ suppressWarnings(as.numeric(.x)))) %>%
  filter(!is.na(Date)) %>%
  filter(rowSums(!is.na(across(-Date))) > 0) %>%
  arrange(Date)

# Drop rows where Date is NA
returns_df <- returns_df %>% filter(!is.na(Date))

# Pick year and stock name
test_plot = returns_df |> filter(Date >= as.Date("2025-01-01")) |> select(Date, `L UN`)

ggplot(data = test_plot,
       aes(x = Date, y = `L UN`)) +
  geom_point() +
  geom_line()
