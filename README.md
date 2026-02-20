# BA_Tools Extension

A comprehensive collection of Revit tools for building automation and project management.

## Structure

- **BA_Tools.tab/** - All tool panels and pushbuttons organized by category
- **Resources/** - Shared XAML styles and resources for consistent UI across all tools

## Shared Resources

All BA_Tools windows use a standardized dark theme interface with consistent styling. Shared styles are defined in:

- **`Resources/BAWindowStyles.xaml`** - Centralized ResourceDictionary with button styles, scrollbar styling, and UI components
- **`Resources/README.md`** - Complete documentation on using shared resources, style reference, and best practices

### Quick Start for Developers

To use shared styles in a new window:

```xml
<Window.Resources>
    <ResourceDictionary>
        <ResourceDictionary.MergedDictionaries>
            <ResourceDictionary Source="../../../../Resources/BAWindowStyles.xaml"/>
        </ResourceDictionary.MergedDictionaries>
    </ResourceDictionary>
</Window.Resources>
```

See `Resources/README.md` for detailed usage instructions.

## Features

- Modern frameless dark UI with BA branding
- Consistent button styles (Primary, Secondary, Close)
- Standardized window layout (Title bar, Content, Footer)
- Shared ResourceDictionary for easy maintenance

## Documentation

- **`Resources/README.md`** - Shared resources guide
- Individual tool documentation in respective tool folders
